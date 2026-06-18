import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import {
  ArrowLeft,
  Megaphone,
  Play,
  Pause,
  Square,
  Pencil,
  Trash2,
  Upload,
  ExternalLink,
} from 'lucide-react';
import {
  PageHeader,
  GlassCard,
  BtnPrimary,
  BtnGhost,
  Badge,
  StatCard,
  InputField,
} from '@/src/components/admin/theme';
import { fetchOutboundAgents } from '@/src/lib/outbound';
import {
  addCampaignLeads,
  deleteCampaign,
  fetchCampaign,
  importCampaignCsv,
  leadStatusColor,
  pauseCampaign,
  startCampaign,
  statusBadgeVariant,
  resetCampaign,
  stopCampaign,
  updateCampaign,
  type Campaign,
  type CampaignLeadRow,
} from '@/src/lib/campaigns';

const selectCls =
  'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

function targetLabel(row: CampaignLeadRow) {
  if (row.lead_name || row.lead_phone) {
    return [row.lead_name, row.lead_phone, row.lead_company].filter(Boolean).join(' · ');
  }
  return row.endpoint || `Lead #${row.lead_id}`;
}

export default function CampaignDetail() {
  const { id } = useParams();
  const campaignId = Number(id);
  const navigate = useNavigate();
  const { token } = useAuth();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [showStart, setShowStart] = useState(false);
  const [showEdit, setShowEdit] = useState(false);
  const [parallel, setParallel] = useState(2);
  const [interCallDelay, setInterCallDelay] = useState(30);
  const [scheduleMode, setScheduleMode] = useState<'now' | 'later'>('now');
  const [scheduleAt, setScheduleAt] = useState('');
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [moreEndpoints, setMoreEndpoints] = useState('');
  const csvRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    if (!token || !campaignId) return;
    fetchCampaign(token, campaignId)
      .then(c => {
        setCampaign(c);
        setEditName(c.name);
        setEditDesc(c.description || '');
        setParallel(c.progress?.max_parallel ?? c.agent_ids?.length ?? 2);
        setInterCallDelay(c.inter_call_delay_sec ?? c.progress?.inter_call_delay_sec ?? 30);
      })
      .catch(e => setErr(e instanceof Error ? e.message : 'Load failed'));
  }, [token, campaignId]);

  useEffect(() => {
    load();
    if (token) fetchOutboundAgents(token).then(setAgents);
  }, [load, token]);

  useEffect(() => {
    if (!campaign || campaign.status !== 'running') return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [campaign?.status, load]);

  const onStart = async () => {
    setErr('');
    try {
      await startCampaign(token, campaignId, {
        max_parallel: parallel,
        inter_call_delay_sec: interCallDelay,
        start_at:
          scheduleMode === 'later' && scheduleAt
            ? new Date(scheduleAt).toISOString()
            : null,
      });
      setMsg(scheduleMode === 'later' ? 'Campaign scheduled' : 'Campaign started');
      setShowStart(false);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Start failed');
    }
  };

  const onPause = async () => {
    await pauseCampaign(token, campaignId);
    setMsg('Campaign paused');
    load();
  };

  const onStop = async () => {
    await stopCampaign(token, campaignId);
    setMsg('Campaign stopped');
    load();
  };

  const onReset = async () => {
    const res = await resetCampaign(token, campaignId);
    setMsg(`Reset ${res.reset} target(s) to pending`);
    load();
  };

  const onDelete = async () => {
    if (!confirm('Delete this campaign and all targets?')) return;
    try {
      await deleteCampaign(token, campaignId);
      navigate('/admin/campaigns');
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Delete failed');
    }
  };

  const onSaveEdit = async () => {
    try {
      await updateCampaign(token, campaignId, {
        name: editName,
        description: editDesc,
      });
      setShowEdit(false);
      setMsg('Campaign updated');
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed');
    }
  };

  const onAddEndpoints = async () => {
    const eps = moreEndpoints.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
    if (!eps.length) return;
    await addCampaignLeads(token, campaignId, { endpoints: eps });
    setMoreEndpoints('');
    setMsg(`Added ${eps.length} target(s)`);
    load();
  };

  const onCsv = async (file: File) => {
    await importCampaignCsv(token, campaignId, file);
    setMsg('CSV imported');
    load();
  };

  if (!campaign) {
    return (
      <div className="p-8 text-zinc-500">{err || 'Loading…'}</div>
    );
  }

  const p = campaign.progress;
  const canEdit = campaign.status !== 'running';
  const leads = campaign.campaign_leads ?? [];
  const fleetAgents = (campaign.agent_ids?.length ? campaign.agent_ids : [campaign.agent_id])
    .map(id => agents.find(a => a.id === id))
    .filter(Boolean);

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      <Link to="/admin/campaigns" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-white mb-4">
        <ArrowLeft className="w-4 h-4" /> All campaigns
      </Link>

      <PageHeader
        title={campaign.name}
        subtitle={campaign.description || 'No description'}
        action={
          <div className="flex flex-wrap gap-2">
            {canEdit && (
              <BtnGhost onClick={() => setShowEdit(true)}><Pencil className="w-4 h-4" /> Edit</BtnGhost>
            )}
            {canEdit && p && p.percent_done > 0 && (
              <BtnGhost onClick={onReset}>Reset targets</BtnGhost>
            )}
            {canEdit && (
              <BtnGhost onClick={onDelete} className="text-red-400 border-red-500/30 hover:bg-red-500/10">
                <Trash2 className="w-4 h-4" /> Delete
              </BtnGhost>
            )}
            {campaign.status === 'running' ? (
              <>
                <BtnGhost onClick={onPause}><Pause className="w-4 h-4" /> Pause</BtnGhost>
                <BtnGhost onClick={onStop}><Square className="w-4 h-4" /> Stop</BtnGhost>
              </>
            ) : (
              <BtnPrimary
                className="from-orange-600 to-amber-600"
                onClick={() => setShowStart(true)}
                disabled={!p?.pending}
              >
                <Play className="w-4 h-4" /> {p?.pending ? 'Start campaign' : 'No pending targets'}
              </BtnPrimary>
            )}
          </div>
        }
      />

      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Megaphone className="w-4 h-4 text-orange-400" />
        <Badge variant={statusBadgeVariant(campaign.status)}>{campaign.status}</Badge>
        {campaign.organization_name && (
          <Badge variant="default">{campaign.organization_name}</Badge>
        )}
        <span className="text-xs text-zinc-600">
          {fleetAgents.length
            ? fleetAgents.map(a => a!.name).join(' · ')
            : `Agent #${campaign.agent_id}`}
        </span>
      </div>

      {p && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <StatCard label="Total" value={p.total} icon={Megaphone} accent="violet" />
          <StatCard label="Completed" value={p.completed} icon={Play} accent="emerald" />
          <StatCard label="In progress" value={p.dialing} icon={Play} accent="cyan" />
          <StatCard label="Remaining" value={p.pending} icon={Pause} accent="amber" />
        </div>
      )}

      {p && (
        <GlassCard className="p-4 mb-6">
          <div className="flex justify-between text-xs text-zinc-500 mb-2">
            <span>Progress</span>
            <span>{p.percent_done}% · {p.failed} failed</span>
          </div>
          <div className="h-2 rounded-full bg-zinc-800 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-violet-600 to-emerald-500 transition-all"
              style={{ width: `${p.percent_done}%` }}
            />
          </div>
          {campaign.status === 'running' && (
            <p className="text-[10px] text-zinc-600 mt-2">
              Active slots: {p.active_slots}/{p.max_parallel ?? parallel}
              {p.inter_call_delay_sec != null ? ` · ${p.inter_call_delay_sec}s between calls` : ''}
              {p.agents_in_cooldown ? ` · ${p.agents_in_cooldown} cooling down` : ''}
            </p>
          )}
        </GlassCard>
      )}

      {showStart && (
        <GlassCard className="p-6 mb-6 space-y-4 border-violet-500/20">
          <h3 className="text-sm font-semibold text-white">Start campaign</h3>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5 block">
              Parallel calls
            </label>
            <input
              type="number"
              min={1}
              max={10}
              className={selectCls}
              value={parallel}
              onChange={e => setParallel(Number(e.target.value))}
            />
            <p className="text-[10px] text-zinc-600 mt-1">
              Max agents dialing at once. Inbound callbacks on ext 700 do not block other agents.
            </p>
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5 block">
              Delay between calls (seconds)
            </label>
            <input
              type="number"
              min={0}
              max={600}
              className={selectCls}
              value={interCallDelay}
              onChange={e => setInterCallDelay(Number(e.target.value) || 0)}
            />
            <p className="text-[10px] text-zinc-600 mt-1">
              Per-agent cooldown after each outbound ends (reduces carrier flagging).
            </p>
          </div>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <input type="radio" checked={scheduleMode === 'now'} onChange={() => setScheduleMode('now')} />
              Start now
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
              <input type="radio" checked={scheduleMode === 'later'} onChange={() => setScheduleMode('later')} />
              Schedule
            </label>
          </div>
          {scheduleMode === 'later' && (
            <input
              type="datetime-local"
              className={selectCls}
              value={scheduleAt}
              onChange={e => setScheduleAt(e.target.value)}
            />
          )}
          <div className="flex gap-2">
            <BtnPrimary className="from-orange-600 to-amber-600" onClick={onStart}>Confirm</BtnPrimary>
            <BtnGhost onClick={() => setShowStart(false)}>Cancel</BtnGhost>
          </div>
        </GlassCard>
      )}

      {showEdit && (
        <GlassCard className="p-6 mb-6 space-y-4">
          <h3 className="text-sm font-semibold text-white">Edit campaign</h3>
          <InputField label="Name" value={editName} onChange={e => setEditName(e.target.value)} />
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Description</label>
            <textarea className={`${selectCls} min-h-[80px]`} value={editDesc} onChange={e => setEditDesc(e.target.value)} />
          </div>
          <div className="flex gap-2">
            <BtnPrimary onClick={onSaveEdit}>Save</BtnPrimary>
            <BtnGhost onClick={() => setShowEdit(false)}>Cancel</BtnGhost>
          </div>
        </GlassCard>
      )}

      {canEdit && (
        <GlassCard className="p-4 mb-6 space-y-3">
          <h3 className="text-sm font-semibold text-white">Add targets</h3>
          <textarea
            className={`${selectCls} font-mono text-xs min-h-[60px]`}
            placeholder="PJSIP/1003 or paste more lines…"
            value={moreEndpoints}
            onChange={e => setMoreEndpoints(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <BtnGhost onClick={onAddEndpoints}>Add lines</BtnGhost>
            <input
              ref={csvRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) onCsv(f).catch(er => setErr(String(er)));
              }}
            />
            <BtnGhost onClick={() => csvRef.current?.click()}>
              <Upload className="w-4 h-4" /> Import CSV
            </BtnGhost>
          </div>
        </GlassCard>
      )}

      <GlassCard className="overflow-hidden">
        <div className="px-4 py-3 border-b border-white/5 text-sm font-semibold text-white">
          Targets ({leads.length})
        </div>
        <div className="max-h-[420px] overflow-y-auto divide-y divide-white/5">
          {leads.map(row => (
            <div key={row.id} className="px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-sm">
              <div className="min-w-0">
                <p className="text-white truncate">{targetLabel(row)}</p>
                {row.endpoint && row.lead_phone && (
                  <p className="text-xs text-zinc-600 font-mono">{row.endpoint}</p>
                )}
                {row.last_error && <p className="text-xs text-red-400 mt-0.5">{row.last_error}</p>}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className={`text-[10px] font-semibold uppercase ${leadStatusColor(row.status)}`}>
                  {row.status}
                </span>
                {row.session_id && (
                  <Link to={`/admin/sessions/${row.session_id}`} className="text-violet-400 hover:text-violet-300">
                    <ExternalLink className="w-4 h-4" />
                  </Link>
                )}
              </div>
            </div>
          ))}
          {leads.length === 0 && (
            <p className="p-4 text-sm text-zinc-600">No targets yet.</p>
          )}
        </div>
      </GlassCard>

      {err && <p className="text-sm text-red-400 mt-4">{err}</p>}
      {msg && <p className="text-sm text-emerald-400 mt-4">{msg}</p>}
    </div>
  );
}
