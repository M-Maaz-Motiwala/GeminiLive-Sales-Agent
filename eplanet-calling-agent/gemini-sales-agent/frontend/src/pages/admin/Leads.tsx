import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Users, Search, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';

const STATUSES = ['new', 'qualified', 'contacted', 'closed', 'lost'];

const selectCls = 'rounded-full border border-white/10 bg-black/40 px-3 py-1 text-[10px] font-semibold uppercase text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 cursor-pointer';

export default function Leads() {
  const { token } = useAuth();
  const [leads, setLeads] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = (status = statusFilter, q = search) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (q.trim()) params.set('search', q.trim());
    const qs = params.toString() ? `?${params}` : '';
    apiFetchList(`/api/leads${qs}`, token).then(setLeads);
  };

  useEffect(() => { load(); }, [token, statusFilter]);

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
      <PageHeader title="Leads" subtitle="CRM leads from calls and agent tools" />

      <div className="flex flex-col sm:flex-row gap-3 mb-6">
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
              <select value={l.status} onChange={e => updateStatus(l, e.target.value)} className={selectCls}>
                {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
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
