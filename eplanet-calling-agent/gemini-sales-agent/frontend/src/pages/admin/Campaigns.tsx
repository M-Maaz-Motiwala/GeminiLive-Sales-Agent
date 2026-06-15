import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Megaphone, PhoneOutgoing, Plus, Upload, ChevronRight } from 'lucide-react';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';
import { fetchOutboundAgents } from '@/src/lib/outbound';
import {
  createCampaign,
  fetchCampaigns,
  importCampaignCsv,
  statusBadgeVariant,
  type Campaign,
} from '@/src/lib/campaigns';

const selectCls =
  'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Campaigns() {
  const { token } = useAuth();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [agentIds, setAgentIds] = useState<number[]>([]);
  const [interCallDelay, setInterCallDelay] = useState(30);
  const [endpoints, setEndpoints] = useState('');
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const csvRef = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => fetchCampaigns(token).then(setCampaigns);

  useEffect(() => {
    if (!token) return;
    load();
    fetchOutboundAgents(token).then(a => {
      setAgents(a);
      if (a.length && agentIds.length === 0) {
        setAgentIds(a.slice(0, Math.min(3, a.length)).map((x: { id: number }) => x.id));
      }
    });
  }, [token]);

  const create = async () => {
    setErr('');
    setMsg('');
    if (!agentIds.length || !name.trim()) {
      setErr('Name and at least one agent are required');
      return;
    }
    setBusy(true);
    try {
      const eps = endpoints.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
      const campaign = await createCampaign(token, {
        name: name.trim(),
        agent_ids: agentIds,
        inter_call_delay_sec: interCallDelay,
        description: description.trim() || undefined,
        endpoints: eps.length ? eps : undefined,
      });
      if (csvFile) {
        await importCampaignCsv(token, campaign.id, csvFile);
        setMsg(`Campaign created with CSV import (${campaign.name})`);
      } else if (!eps.length) {
        setErr('Add endpoints, paste numbers, or upload a CSV');
        setBusy(false);
        return;
      } else {
        setMsg('Campaign created');
      }
      setName('');
      setDescription('');
      setEndpoints('');
      setCsvFile(null);
      if (csvRef.current) csvRef.current.value = '';
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Create failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      <PageHeader
        title="Campaigns"
        subtitle="Fleet outbound — multiple sales agents, adjustable delay between calls, callback routing on 700"
        action={
          <Link to="/admin/outbound">
            <BtnGhost><PhoneOutgoing className="w-4 h-4" /> Quick dial</BtnGhost>
          </Link>
        }
      />

      <GlassCard className="p-6 mb-8 space-y-4">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <Plus className="w-4 h-4 text-violet-400" /> New campaign
        </h2>
        <input className={selectCls} placeholder="Campaign name" value={name} onChange={e => setName(e.target.value)} />
        <textarea
          className={`${selectCls} min-h-[72px]`}
          placeholder="Description — goal, audience, notes for your team…"
          value={description}
          onChange={e => setDescription(e.target.value)}
        />
        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5 block">
            Sales agents (fleet)
          </label>
          <div className="flex flex-wrap gap-2">
            {agents.map(a => {
              const on = agentIds.includes(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() =>
                    setAgentIds(prev =>
                      on ? prev.filter(id => id !== a.id) : [...prev, a.id],
                    )
                  }
                  className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                    on
                      ? 'border-violet-500/60 bg-violet-500/20 text-violet-200'
                      : 'border-white/10 bg-black/30 text-zinc-400 hover:border-white/20'
                  }`}
                >
                  {a.name}
                </button>
              );
            })}
          </div>
        </div>

        <label className="block space-y-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
            Delay between calls (seconds)
          </span>
          <input
            type="number"
            min={0}
            max={600}
            className={selectCls}
            value={interCallDelay}
            onChange={e => setInterCallDelay(Number(e.target.value) || 0)}
          />
          <p className="text-[10px] text-zinc-600">Per-agent cooldown after each call ends (anti-flagging).</p>
        </label>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5 block">
            Targets (one per line)
          </label>
          <textarea
            className={`${selectCls} font-mono text-xs min-h-[80px]`}
            value={endpoints}
            onChange={e => setEndpoints(e.target.value)}
            placeholder={'1001\n1002\nPJSIP/1003\nor +15551234567 (trunk mode)'}
          />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={csvRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={e => setCsvFile(e.target.files?.[0] ?? null)}
          />
          <BtnGhost type="button" onClick={() => csvRef.current?.click()}>
            <Upload className="w-4 h-4" />
            {csvFile ? csvFile.name : 'Upload CSV'}
          </BtnGhost>
          <span className="text-[10px] text-zinc-600">
            CSV columns: phone, name, email, company, endpoint
          </span>
        </div>

        <BtnPrimary onClick={create} disabled={busy}>
          {busy ? 'Creating…' : 'Create campaign'}
        </BtnPrimary>
        {err && <p className="text-sm text-red-400">{err}</p>}
        {msg && <p className="text-sm text-emerald-400">{msg}</p>}
      </GlassCard>

      <div className="space-y-3">
        {campaigns.map(c => (
          <Link key={c.id} to={`/admin/campaigns/${c.id}`}>
            <GlassCard className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:border-violet-500/30 transition-colors cursor-pointer">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Megaphone className="w-4 h-4 text-orange-400 shrink-0" />
                  <span className="font-medium text-white truncate">{c.name}</span>
                  <Badge variant={statusBadgeVariant(c.status)}>{c.status}</Badge>
                </div>
                {c.description && (
                  <p className="text-xs text-zinc-500 mt-1 line-clamp-2">{c.description}</p>
                )}
                <p className="text-xs text-zinc-600 mt-1">
                  {c.lead_count} targets
                  {c.progress && (
                    <> · {c.progress.percent_done}% done · {c.progress.pending} left</>
                  )}
                </p>
              </div>
              <ChevronRight className="w-5 h-5 text-zinc-600 shrink-0" />
            </GlassCard>
          </Link>
        ))}
        {campaigns.length === 0 && (
          <p className="text-sm text-zinc-600">No campaigns yet. Create one above.</p>
        )}
      </div>
    </div>
  );
}
