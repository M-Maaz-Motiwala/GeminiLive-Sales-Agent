import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Megaphone, PhoneOutgoing, Plus } from 'lucide-react';
import { apiFetch, apiFetchList } from '@/src/lib/api';
import { fetchOutboundAgents } from '@/src/lib/outbound';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';

const selectCls =
  'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Campaigns() {
  const { token } = useAuth();
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [name, setName] = useState('Lab dual-phone demo');
  const [agentId, setAgentId] = useState<number | ''>('');
  const [endpoints, setEndpoints] = useState('PJSIP/1001\nPJSIP/1002');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');

  const load = () => {
    apiFetchList('/api/campaigns', token).then(setCampaigns);
    fetchOutboundAgents(token).then(a => {
      setAgents(a);
      if (a.length && agentId === '') setAgentId(a[0].id);
    });
    apiFetchList('/api/leads', token).then(setLeads);
  };

  useEffect(() => { if (token) load(); }, [token]);

  const create = async () => {
    setErr('');
    setMsg('');
    if (!agentId || !name.trim()) {
      setErr('Name and agent required');
      return;
    }
    const eps = endpoints.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    try {
      await apiFetch('/api/campaigns', token, {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          agent_id: agentId,
          description: 'Phase 2a lab campaign',
          endpoints: eps,
        }),
      });
      setMsg('Campaign created');
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Create failed');
    }
  };

  const dialCampaign = async (id: number, parallel = 2) => {
    setErr('');
    setMsg('');
    try {
      const res = await apiFetch<{ dialed: number; results: any[] }>(
        `/api/campaigns/${id}/dial`,
        token,
        { method: 'POST', body: JSON.stringify({ max_parallel: parallel }) },
      );
      setMsg(`Dialed ${res.results?.length ?? 0} target(s) — check phones 1001 & 1002`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Dial failed');
    }
  };

  return (
    <div className="p-6 lg:p-8 max-w-4xl">
      <PageHeader
        title="Campaigns"
        subtitle="Batch outbound — lab demo with 1001 + 1002, trunk-ready when DID arrives"
        action={
          <Link to="/admin/outbound">
            <BtnGhost><PhoneOutgoing className="w-4 h-4" /> Quick dial</BtnGhost>
          </Link>
        }
      />

      <GlassCard className="p-6 mb-6 space-y-4">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <Plus className="w-4 h-4 text-violet-400" /> New lab campaign
        </h2>
        <input className={selectCls} placeholder="Campaign name" value={name} onChange={e => setName(e.target.value)} />
        <select className={selectCls} value={agentId} onChange={e => setAgentId(Number(e.target.value))}>
          {agents.map(a => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <textarea
          className={`${selectCls} font-mono text-xs min-h-[80px]`}
          value={endpoints}
          onChange={e => setEndpoints(e.target.value)}
          placeholder="PJSIP/1001&#10;PJSIP/1002"
        />
        <p className="text-[10px] text-zinc-600">One endpoint per line — register Zoiper as 1001 and 1002 on same Wi‑Fi.</p>
        <BtnPrimary onClick={create}>Create campaign</BtnPrimary>
        {err && <p className="text-sm text-red-400">{err}</p>}
        {msg && <p className="text-sm text-emerald-400">{msg}</p>}
      </GlassCard>

      <div className="space-y-3">
        {campaigns.map(c => (
          <GlassCard key={c.id} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <Megaphone className="w-4 h-4 text-orange-400" />
                <span className="font-medium text-white">{c.name}</span>
                <Badge variant="default">{c.status}</Badge>
              </div>
              <p className="text-xs text-zinc-500 mt-1">{c.lead_count} targets · agent #{c.agent_id}</p>
            </div>
            <BtnPrimary
              className="bg-gradient-to-r from-orange-600 to-amber-600 shrink-0"
              onClick={() => dialCampaign(c.id, 2)}
            >
              Dial all (2 parallel)
            </BtnPrimary>
          </GlassCard>
        ))}
        {campaigns.length === 0 && (
          <p className="text-sm text-zinc-600">No campaigns yet. Create one above for dual-phone demo.</p>
        )}
      </div>
    </div>
  );
}
