import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Users, Search, ExternalLink, PhoneOutgoing } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard, BtnGhost } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';
import { dialOutbound, fetchOutboundAgents } from '@/src/lib/outbound';
import OrgFilter from '@/src/components/admin/OrgFilter';

const STATUSES = ['new', 'qualified', 'contacted', 'closed', 'lost'];

const selectCls = 'rounded-full border border-white/10 bg-black/40 px-3 py-1 text-[10px] font-semibold uppercase text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 cursor-pointer';

export default function Leads() {
  const { token } = useAuth();
  const [leads, setLeads] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [search, setSearch] = useState('');
  const [outboundAgents, setOutboundAgents] = useState<any[]>([]);
  const [outboundAgentId, setOutboundAgentId] = useState<number | null>(null);
  const [dialingId, setDialingId] = useState<number | null>(null);
  const [dialMsg, setDialMsg] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = (status = statusFilter, q = search, org = organizationId) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (q.trim()) params.set('search', q.trim());
    if (org) params.set('organization_id', org);
    const qs = params.toString() ? `?${params}` : '';
    apiFetchList(`/api/leads${qs}`, token).then(setLeads);
  };

  useEffect(() => {
    load();
    if (token) {
      fetchOutboundAgents(token).then(agents => {
        setOutboundAgents(agents);
        const pool = organizationId
          ? agents.filter(a => String(a.organization_id) === organizationId)
          : agents;
        setOutboundAgentId(pool[0]?.id ?? agents[0]?.id ?? null);
      });
    }
  }, [token, statusFilter, organizationId]);

  useEffect(() => {
    if (!organizationId) return;
    const pool = outboundAgents.filter(a => String(a.organization_id) === organizationId);
    setOutboundAgentId(pool[0]?.id ?? null);
  }, [organizationId, outboundAgents]);

  const callLead = async (lead: any) => {
    if (!outboundAgentId) {
      setDialMsg('No outbound agent — run bootstrap or open Outbound Calls.');
      return;
    }
    setDialingId(lead.id);
    setDialMsg('');
    try {
      await dialOutbound(token, { agent_id: outboundAgentId, lead_id: lead.id });
      setDialMsg(`Dialing lead #${lead.id} — answer on Zoiper 1001.`);
    } catch (e) {
      setDialMsg(e instanceof Error ? e.message : 'Dial failed');
    } finally {
      setDialingId(null);
    }
  };

  const updateStatus = async (lead: any, status: string) => {
    await fetch(`${API_BASE}/api/leads/${lead.id}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({ status }),
    });
    load();
  };

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Leads"
        subtitle="CRM leads from calls — use Call to dial with lead context (outbound)"
        action={
          <Link to="/admin/outbound">
            <BtnGhost>
              <PhoneOutgoing className="w-4 h-4" /> Outbound Calls
            </BtnGhost>
          </Link>
        }
      />

      {dialMsg && (
        <p className="text-sm text-violet-300 bg-violet-500/10 border border-violet-500/20 rounded-xl px-4 py-2 mb-4">
          {dialMsg}
        </p>
      )}

      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <OrgFilter value={organizationId} onChange={setOrganizationId} className="sm:w-56" />
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500" />
          <input
            placeholder="Search name, email, company…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && load(statusFilter, search)}
            className="w-full pl-9 pr-3 py-2 rounded-xl border border-white/10 bg-black/40 text-sm text-white placeholder:text-zinc-600"
          />
        </div>
        <button
          onClick={() => load(statusFilter, search)}
          className="px-4 py-2 rounded-xl text-xs font-semibold border border-white/10 text-zinc-300 hover:bg-white/5"
        >
          Search
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        <FilterBtn active={statusFilter === ''} onClick={() => setStatusFilter('')}>All</FilterBtn>
        {STATUSES.map(s => (
          <FilterBtn key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>{s}</FilterBtn>
        ))}
      </div>

      <div className="space-y-3">
        {leads.map(l => (
          <GlassCard key={l.id} className="p-4">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-300 shrink-0">
                  <Users className="w-4 h-4" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-white">{l.name || '(no name)'}</div>
                  <div className="text-xs text-zinc-500 mt-0.5">
                    {[l.email, l.phone, l.company].filter(Boolean).join(' · ') || 'No contact details'}
                    {l.organization_name && <> · <span className="text-violet-400/80">{l.organization_name}</span></>}
                  </div>
                  {l.notes && (
                    <p className="text-xs text-zinc-400 mt-2 line-clamp-2 leading-relaxed">{l.notes}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    {l.source_session_id && (
                      <Link
                        to={`/admin/sessions/${l.source_session_id}`}
                        className="text-[10px] text-violet-400 hover:underline flex items-center gap-0.5"
                      >
                        Session #{l.source_session_id} <ExternalLink className="w-2.5 h-2.5" />
                      </Link>
                    )}
                    {(l.tags || []).map((t: string) => (
                      <span key={t} className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-zinc-500">{t}</span>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex flex-col sm:items-end gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => callLead(l)}
                  disabled={dialingId === l.id || !outboundAgentId}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-semibold uppercase tracking-wide border border-orange-500/30 text-orange-300 hover:bg-orange-500/10 disabled:opacity-50"
                >
                  <PhoneOutgoing className="w-3.5 h-3.5" />
                  {dialingId === l.id ? 'Dialing…' : 'Call'}
                </button>
                <select value={l.status} onChange={e => updateStatus(l, e.target.value)} className={selectCls}>
                  {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
          </GlassCard>
        ))}
        {leads.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">
            No leads yet. They appear when the agent uses create_lead or after lead-qualification calls end.
          </GlassCard>
        )}
      </div>
    </div>
  );
}

function FilterBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-3 py-1.5 rounded-xl text-[10px] font-semibold uppercase tracking-wide transition-all',
        active
          ? 'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white shadow-lg shadow-violet-900/30'
          : 'border border-white/10 text-zinc-400 hover:bg-white/5',
      )}
    >
      {children}
    </button>
  );
}
