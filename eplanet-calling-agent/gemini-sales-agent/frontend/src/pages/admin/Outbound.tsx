import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { PhoneOutgoing, Radio, AlertCircle, Wifi, RefreshCw, PhoneOff } from 'lucide-react';
import { API_BASE, apiFetchList, apiFetchPublic } from '@/src/lib/api';
import { appendOrgParam } from '@/src/components/admin/OrgFilter';
import {
  clearStoredActiveDials,
  DEFAULT_LAB_ENDPOINT,
  DIAL_PHASE_ORDER,
  dialBatch,
  dialOutbound,
  fetchDialStatus,
  fetchOutboundAgents,
  fetchOutboundStatus,
  hangupOutboundDial,
  loadStoredActiveDials,
  normalizeDialPhase,
  storeActiveDials,
  type DialTrackerState,
  type OutboundAgent,
} from '@/src/lib/outbound';
import { PageHeader, GlassCard, BtnPrimary, Badge } from '@/src/components/admin/theme';

function mergeDials(prev: DialTrackerState[], incoming: DialTrackerState[]): DialTrackerState[] {
  const map = new Map(prev.map(d => [d.channel_id, d]));
  for (const row of incoming) {
    if (!row.channel_id) continue;
    const existing = map.get(row.channel_id);
    if (existing?.terminal && row.terminal) {
      map.set(row.channel_id, existing);
    } else {
      map.set(row.channel_id, { ...existing, ...row });
    }
  }
  return Array.from(map.values());
}

function DialProgressCard({
  dial,
  isTrunk,
  sipUser1001,
  hangingUp,
  onHangup,
}: {
  dial: DialTrackerState;
  isTrunk: boolean;
  sipUser1001: string;
  hangingUp: boolean;
  onHangup: (channelId: string) => void;
}) {
  const current = normalizeDialPhase(dial.dial_phase);
  const ci = DIAL_PHASE_ORDER.indexOf(current as (typeof DIAL_PHASE_ORDER)[number]);

  return (
    <div className="rounded-xl border border-white/10 bg-black/30 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-white font-medium truncate">{dial.label}</p>
          <p className="text-xs text-zinc-500 font-mono truncate mt-0.5">
            {dial.endpoint || '—'}
          </p>
        </div>
        {!dial.terminal && (
          <div className="flex items-center gap-2 shrink-0">
            <Badge variant="live" className="text-[9px]">Live</Badge>
            <button
              type="button"
              disabled={hangingUp}
              onClick={() => onHangup(dial.channel_id)}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium border border-red-500/40 text-red-300 hover:bg-red-500/10 disabled:opacity-50"
            >
              <PhoneOff className="w-3.5 h-3.5" />
              End call
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 text-[10px]">
        {DIAL_PHASE_ORDER.map(phase => {
          const pi = DIAL_PHASE_ORDER.indexOf(phase);
          const done = pi < ci || (phase === 'ended' && dial.terminal);
          const active = phase === current;
          const label =
            phase === 'ringing'
              ? 'Ringing'
              : phase === 'connecting'
                ? 'Connecting'
                : phase === 'in_call'
                  ? 'In call'
                  : 'Ended';
          return (
            <span
              key={phase}
              className={`px-2 py-1 rounded-md border ${
                active
                  ? 'border-orange-400/50 bg-orange-500/15 text-orange-200'
                  : done
                    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                    : 'border-white/5 text-zinc-600'
              }`}
            >
              {label}
            </span>
          );
        })}
      </div>

      {dial.outcome && (
        <p className="text-xs text-zinc-400">
          Result:{' '}
          <span className="text-white capitalize">{dial.outcome.replace(/_/g, ' ')}</span>
          {dial.hangup_cause_txt ? ` (${dial.hangup_cause_txt})` : ''}
        </p>
      )}
      {dial.session_id && (
        <Link
          to={`/admin/sessions/${dial.session_id}`}
          className="text-xs text-violet-400 hover:underline inline-block"
        >
          Open session #{dial.session_id} →
        </Link>
      )}
      {!isTrunk && !dial.terminal && (
        <p className="text-[10px] text-zinc-600">
          Lab mode: answer on Zoiper extension {sipUser1001} when it rings.
        </p>
      )}
    </div>
  );
}

export default function Outbound() {
  const { token } = useAuth();
  const [searchParams] = useSearchParams();
  const [agents, setAgents] = useState<OutboundAgent[]>([]);
  const [organizations, setOrganizations] = useState<any[]>([]);
  const [organizationId, setOrganizationId] = useState('');
  const [leads, setLeads] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [info, setInfo] = useState<any>(null);
  const [agentId, setAgentId] = useState<number | ''>('');
  const [leadId, setLeadId] = useState<number | ''>('');
  const [endpoint, setEndpoint] = useState(DEFAULT_LAB_ENDPOINT);
  const [connectExperience, setConnectExperience] = useState<'auto_greeting' | 'comfort_tone'>('auto_greeting');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [dialing, setDialing] = useState(false);
  const [activeDials, setActiveDials] = useState<DialTrackerState[]>([]);
  const [hangingUpId, setHangingUpId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bridgeInfo, setBridgeInfo] = useState<{ active_calls?: number; max_concurrent?: number }>({});
  const endpointInitialized = useRef(false);
  const isTrunk = (info?.outbound_mode || '').toLowerCase() === 'trunk';

  const liveDials = activeDials.filter(d => !d.terminal);

  const filteredAgents = useMemo(
    () =>
      organizationId
        ? agents.filter(a => String(a.organization_id) === organizationId)
        : [],
    [agents, organizationId],
  );

  const selectedOrg = organizations.find(o => String(o.id) === organizationId);

  const filteredLeads = useMemo(
    () =>
      organizationId
        ? leads.filter(l => !l.organization_id || String(l.organization_id) === organizationId)
        : leads,
    [leads, organizationId],
  );

  const onOrganizationChange = (nextOrgId: string) => {
    setOrganizationId(nextOrgId);
    const pool = agents.filter(a => String(a.organization_id) === nextOrgId);
    const paramAgent = searchParams.get('agent_id');
    const preferred = paramAgent
      ? pool.find(a => String(a.id) === paramAgent)?.id
      : pool[0]?.id;
    setAgentId(preferred ?? '');
    setLeadId(prev => {
      if (prev === '') return '';
      const ok = leads.some(
        l => l.id === prev && (!l.organization_id || String(l.organization_id) === nextOrgId),
      );
      return ok ? prev : '';
    });
  };

  const syncDials = useCallback((updater: DialTrackerState[] | ((prev: DialTrackerState[]) => DialTrackerState[])) => {
    setActiveDials(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      storeActiveDials(next);
      return next;
    });
  }, []);

  const load = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [agentList, orgList, leadList, sessionList, sysInfo, obStatus] = await Promise.all([
        fetchOutboundAgents(token),
        apiFetchList('/api/organizations', token),
        apiFetchList(appendOrgParam('/api/leads', organizationId), token),
        apiFetchList(appendOrgParam('/api/sessions?limit=20', organizationId), token),
        apiFetchPublic('/api/system/info'),
        fetchOutboundStatus(token).catch(() => ({})),
      ]);
      setBridgeInfo(obStatus?.bridge || {});
      const fromBridge = (obStatus?.active_dials || []).filter(d => !d.terminal);
      if (fromBridge.length) {
        syncDials(prev => mergeDials(prev, fromBridge));
      }
      setAgents(agentList);
      setOrganizations(orgList);
      setLeads(leadList);
      setSessions(
        sessionList.filter(
          (s: any) => s.meta?.direction === 'outbound' || s.channel_type === 'outbound',
        ),
      );
      setInfo(sysInfo);
      const paramAgent = searchParams.get('agent_id');
      const paramLead = searchParams.get('lead_id');
      if (orgList.length && !organizationId) {
        const fromAgent = paramAgent
          ? agentList.find(a => String(a.id) === paramAgent)?.organization_id
          : agentList[0]?.organization_id;
        const oid = fromAgent ? String(fromAgent) : String(orgList[0].id);
        setOrganizationId(oid);
        const pool = agentList.filter(a => String(a.organization_id) === oid);
        const preferred = paramAgent
          ? pool.find(a => String(a.id) === paramAgent)?.id
          : pool[0]?.id;
        setAgentId(preferred ?? '');
      } else if (organizationId && agentList.length) {
        const pool = agentList.filter(a => String(a.organization_id) === organizationId);
        if (!pool.some(a => a.id === agentId)) {
          const preferred = paramAgent
            ? pool.find(a => String(a.id) === paramAgent)?.id
            : pool[0]?.id;
          setAgentId(preferred ?? '');
        }
      }
      if (paramLead) setLeadId(Number(paramLead));
      if (!endpointInitialized.current) {
        const trunk = (sysInfo?.outbound_mode || '').toLowerCase() === 'trunk';
        setEndpoint(trunk ? '' : (sysInfo?.outbound_lab_endpoint || DEFAULT_LAB_ENDPOINT));
        endpointInitialized.current = true;
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const poll = setInterval(load, 5000);
    return () => clearInterval(poll);
  }, [token, searchParams, organizationId]);

  useEffect(() => {
    if (!token || !organizationId) return;
    apiFetchList(appendOrgParam('/api/leads', organizationId), token).then(setLeads);
  }, [token, organizationId]);

  useEffect(() => {
    if (!token) return;
    const stored = loadStoredActiveDials();
    if (!stored.length) return;
    Promise.all(
      stored.map(s =>
        fetchDialStatus(token, s.channel_id).catch(() => ({
          ...s,
          dial_phase: 'ended',
          label: 'Call ended',
          terminal: true,
        })),
      ),
    ).then(rows => {
      const live = rows.filter(r => !r.terminal);
      syncDials(prev => mergeDials(prev, rows));
      if (live.length) setStatus(live[live.length - 1].label);
      if (!live.length) clearStoredActiveDials();
    });
  }, [token, syncDials]);

  useEffect(() => {
    if (!token || !liveDials.length) return;
    let cancelled = false;
    const pollAll = async () => {
      try {
        const rows = await Promise.all(
          liveDials.map(d =>
            fetchDialStatus(token, d.channel_id).catch(() => d),
          ),
        );
        if (cancelled) return;
        syncDials(prev => mergeDials(prev, rows));
        const stillLive = rows.filter(r => !r.terminal);
        if (stillLive.length) {
          setStatus(stillLive[stillLive.length - 1].label);
        } else {
          clearStoredActiveDials();
          load();
        }
      } catch {
        /* keep last known */
      }
    };
    pollAll();
    const id = setInterval(pollAll, 1500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [token, liveDials.map(d => d.channel_id).join(','), syncDials]);

  const hangup = async (channelId: string) => {
    if (!token) return;
    setHangingUpId(channelId);
    setError('');
    try {
      const row = await hangupOutboundDial(token, channelId);
      syncDials(prev =>
        mergeDials(prev, [{ ...row, channel_id: channelId, terminal: true, dial_phase: 'ended' }]),
      );
      setTimeout(() => {
        syncDials(prev => prev.filter(d => d.channel_id !== channelId || !d.terminal));
        load();
      }, 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Hangup failed');
    } finally {
      setHangingUpId(null);
    }
  };

  const dial = async () => {
    if (!agentId) {
      setError('Select an outbound agent');
      return;
    }
    setError('');
    setStatus('');
    setDialing(true);
    try {
      const res = await dialOutbound(token, {
        agent_id: Number(agentId),
        ...(endpoint.trim() ? { endpoint: endpoint.trim() } : {}),
        ...(leadId !== '' ? { lead_id: Number(leadId) } : {}),
        connect_experience: connectExperience,
      });
      const channelId = res.bridge?.channel_id;
      if (channelId) {
        const initial: DialTrackerState = {
          channel_id: channelId,
          dial_phase: res.bridge?.dial_phase || 'ringing',
          label: res.bridge?.label || 'Ringing prospect…',
          endpoint: res.endpoint,
          terminal: false,
        };
        syncDials(prev => mergeDials(prev, [initial]));
        setStatus(initial.label);
      } else {
        setStatus(`Dialing ${res.endpoint}…`);
      }
      setTimeout(() => load(), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Dial failed');
    } finally {
      setDialing(false);
    }
  };

  const sipServer = info?.sip_server || info?.external_ip || '—';
  const sipUser1001 = info?.sip_user_1001 || '1001';
  const sipPass1001 = info?.sip_pass_1001 || '1001pass';

  const selectCls =
    'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

  return (
    <div className="p-6 lg:p-8 max-w-5xl">
      <PageHeader
        title="Outbound Calls"
        subtitle={
          isTrunk
            ? 'Place outbound calls via PSTN trunk — live progress for each active dial'
            : 'Place cold calls from the CRM — your mobile Zoiper (ext 1001) receives the call'
        }
        action={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => load()}
              className="p-2 rounded-xl border border-white/10 text-zinc-400 hover:text-white hover:bg-white/5"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <Link to="/admin/sessions">
              <Badge variant="live">
                <Radio className="w-3 h-3 inline mr-1" />
                Sessions
              </Badge>
            </Link>
          </div>
        }
      />

      {liveDials.length > 0 && (
        <GlassCard className="p-5 mb-6 space-y-3 border-orange-500/20">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-white">
              Active calls ({liveDials.length})
            </h2>
            {bridgeInfo.max_concurrent != null && (
              <span className="text-[10px] text-zinc-500">
                Bridge {bridgeInfo.active_calls ?? 0} / {bridgeInfo.max_concurrent}
              </span>
            )}
          </div>
          <div className="space-y-3">
            {liveDials.map(dial => (
              <DialProgressCard
                key={dial.channel_id}
                dial={dial}
                isTrunk={isTrunk}
                sipUser1001={sipUser1001}
                hangingUp={hangingUpId === dial.channel_id}
                onHangup={hangup}
              />
            ))}
          </div>
        </GlassCard>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {!isTrunk && (
            <GlassCard className="p-6 space-y-4 border-orange-500/15">
              <div className="flex items-center gap-2 text-orange-300">
                <PhoneOutgoing className="w-5 h-5" />
                <h2 className="text-sm font-semibold text-white">1. Register phone (prospect)</h2>
              </div>
              <dl className="grid sm:grid-cols-2 gap-2 text-sm">
                {[
                  ['SIP server', sipServer],
                  ['Port', `${info?.sip_port || 5060} UDP`],
                  ['Codec', info?.sip_codec_label || 'G.711 μ-law'],
                  ['Password rule', '{ext}pass (e.g. 1003pass)'],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 p-2 rounded-lg bg-black/30 border border-white/5">
                    <dt className="text-zinc-500 text-xs">{k}</dt>
                    <dd className="font-mono text-orange-300/90 text-xs text-right">{v}</dd>
                  </div>
                ))}
              </dl>
              <div className="overflow-x-auto rounded-lg border border-white/10">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/10 bg-white/[0.02]">
                      <th className="p-2 text-left text-zinc-500">Ext</th>
                      <th className="p-2 text-left text-zinc-500">Username</th>
                      <th className="p-2 text-left text-zinc-500">Password</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(info?.lab_extensions as { extension: string; username: string; password: string }[] | undefined)?.map(
                      row => (
                        <tr key={row.extension} className="border-b border-white/5 last:border-0">
                          <td className="p-2 font-mono text-white">{row.extension}</td>
                          <td className="p-2 font-mono text-orange-300/90">{row.username}</td>
                          <td className="p-2 font-mono text-zinc-400">{row.password}</td>
                        </tr>
                      ),
                    ) ?? (
                      <tr>
                        <td className="p-2 font-mono text-white">1001</td>
                        <td className="p-2 font-mono text-orange-300/90">{sipUser1001}</td>
                        <td className="p-2 font-mono text-zinc-400">{sipPass1001}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="text-[10px] text-zinc-600 flex items-center gap-1">
                <Wifi className="w-3 h-3" /> One Zoiper account per phone. Same Wi‑Fi as this PC — use SIP server above, not 127.0.0.1. Wait for Registered.
              </p>
            </GlassCard>
          )}

          <GlassCard className="p-6 space-y-4">
            <div className="flex items-center gap-2 text-violet-300">
              <PhoneOutgoing className="w-5 h-5" />
              <h2 className="text-sm font-semibold text-white">
                {isTrunk ? 'Place call from CRM' : '2. Place call from CRM'}
              </h2>
            </div>

            {agents.length === 0 ? (
              <div className="space-y-3">
                <p className="text-sm text-amber-400/90 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  No outbound agents found. Create a sales agent under an organization first.
                </p>
                <Link to="/admin/agents" className="text-xs text-violet-400 hover:underline">
                  Go to AI Agents →
                </Link>
              </div>
            ) : organizations.length === 0 ? (
              <p className="text-sm text-amber-400/90">
                No organizations yet.{' '}
                <Link to="/admin/organizations" className="text-violet-400 hover:underline">Create one</Link> first.
              </p>
            ) : (
              <>
                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">Organization</span>
                  <select
                    className={selectCls}
                    value={organizationId}
                    onChange={e => onOrganizationChange(e.target.value)}
                  >
                    <option value="">Select organization…</option>
                    {organizations.map(o => (
                      <option key={o.id} value={o.id}>
                        {o.name} — DID {o.did}
                      </option>
                    ))}
                  </select>
                  {selectedOrg && (
                    <p className="text-[10px] text-zinc-600">Outbound caller ID: {selectedOrg.did}</p>
                  )}
                </label>

                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">Outbound agent</span>
                  <select
                    className={selectCls}
                    value={agentId}
                    onChange={e => setAgentId(e.target.value ? Number(e.target.value) : '')}
                    disabled={!organizationId || filteredAgents.length === 0}
                  >
                    {!organizationId ? (
                      <option value="">Select organization first</option>
                    ) : filteredAgents.length === 0 ? (
                      <option value="">No agents for this org</option>
                    ) : (
                      filteredAgents.map(a => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))
                    )}
                  </select>
                </label>

                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">Lead (optional — CRM context in prompt)</span>
                  <select
                    className={selectCls}
                    value={leadId}
                    onChange={e => setLeadId(e.target.value ? Number(e.target.value) : '')}
                  >
                    <option value="">— No lead —</option>
                    {filteredLeads.map(l => (
                      <option key={l.id} value={l.id}>
                        {l.name || '(no name)'} — {l.phone || l.email || `lead #${l.id}`}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">Pickup experience</span>
                  <select
                    className={selectCls}
                    value={connectExperience}
                    onChange={e => setConnectExperience((e.target.value as 'auto_greeting' | 'comfort_tone') || 'auto_greeting')}
                  >
                    <option value="auto_greeting">Auto greeting (fast agent hello)</option>
                    <option value="comfort_tone">Comfort tone (hold tone while connecting)</option>
                  </select>
                </label>

                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">
                    {isTrunk ? 'Phone number (E.164)' : 'Dial target (ARI endpoint)'}
                  </span>
                  <input
                    className={selectCls}
                    value={endpoint}
                    onChange={e => setEndpoint(e.target.value)}
                    placeholder={isTrunk ? '+12105551234 or +923351234567' : DEFAULT_LAB_ENDPOINT}
                  />
                </label>

                <div className="flex flex-wrap gap-2">
                  <BtnPrimary
                    onClick={dial}
                    disabled={dialing || !agentId}
                    className="bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500"
                  >
                    {dialing ? 'Originating…' : 'Dial now'}
                  </BtnPrimary>
                  {!isTrunk && (
                    <BtnPrimary
                      onClick={async () => {
                        if (!agentId) return;
                        setDialing(true);
                        setError('');
                        try {
                          const res = await dialBatch(token, {
                            agent_id: Number(agentId),
                            endpoints: ['PJSIP/1001', 'PJSIP/1002'],
                          });
                          setStatus(`Batch: ${res.dialed} ok, ${res.failed} failed`);
                          load();
                        } catch (e) {
                          setError(e instanceof Error ? e.message : 'Batch failed');
                        } finally {
                          setDialing(false);
                        }
                      }}
                      disabled={dialing || !agentId}
                      className="bg-violet-700 hover:bg-violet-600"
                    >
                      Dial 1001 + 1002
                    </BtnPrimary>
                  )}
                </div>
              </>
            )}

            {error && <p className="text-sm text-red-400">{error}</p>}
            {status && !liveDials.length && <p className="text-sm text-emerald-400/90">{status}</p>}
          </GlassCard>
        </div>

        <div className="space-y-6">
          <GlassCard className="p-5">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">Recent outbound sessions</h3>
            {sessions.length === 0 ? (
              <p className="text-xs text-zinc-600">No outbound sessions yet.</p>
            ) : (
              <ul className="space-y-2">
                {sessions.slice(0, 5).map(s => (
                  <li key={s.id}>
                    <Link
                      to={`/admin/sessions/${s.id}`}
                      className="block p-2 rounded-lg hover:bg-white/5 border border-white/5 text-xs"
                    >
                      <span className="text-white font-medium">#{s.id}</span>
                      <span className="text-zinc-500 ml-2">{s.agent?.name?.split('—')[0]?.trim()}</span>
                      <Badge variant={s.status === 'active' ? 'live' : 'success'} className="ml-2 text-[9px]">
                        {s.status}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <Link to="/admin/sessions" className="text-[10px] text-violet-400 hover:underline mt-3 inline-block">
              All sessions →
            </Link>
          </GlassCard>

          <GlassCard className="p-5 text-xs text-zinc-500 space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Per-organization outbound</h3>
            <p>
              <Link to="/admin/organizations" className="text-violet-400 hover:underline">Organizations</Link> — register DIDs
            </p>
            <p>
              <Link to="/admin/agents" className="text-violet-400 hover:underline">AI Agents</Link> — prompts, voice, tools per org
            </p>
            <p>
              <Link to="/admin/documents" className="text-violet-400 hover:underline">Knowledge base</Link> — org-scoped KB
            </p>
            <p className="text-[10px] text-zinc-600 pt-2 border-t border-white/5 font-mono">
              POST {API_BASE}/api/outbound/dial
            </p>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
