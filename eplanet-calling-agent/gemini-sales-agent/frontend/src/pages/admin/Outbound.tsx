import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { PhoneOutgoing, Radio, AlertCircle, Wifi, RefreshCw } from 'lucide-react';
import { API_BASE, apiFetchList, apiFetchPublic } from '@/src/lib/api';
import {
  DEFAULT_LAB_ENDPOINT,
  dialBatch,
  dialOutbound,
  fetchOutboundAgents,
  fetchOutboundStatus,
  type OutboundAgent,
} from '@/src/lib/outbound';
import { PageHeader, GlassCard, BtnPrimary, Badge } from '@/src/components/admin/theme';

export default function Outbound() {
  const { token } = useAuth();
  const [searchParams] = useSearchParams();
  const [agents, setAgents] = useState<OutboundAgent[]>([]);
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
  const [loading, setLoading] = useState(true);
  const [bridgeInfo, setBridgeInfo] = useState<{ active_calls?: number; max_concurrent?: number }>({});
  const endpointInitialized = useRef(false);
  const isTrunk = (info?.outbound_mode || '').toLowerCase() === 'trunk';

  const load = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [agentList, leadList, sessionList, sysInfo, obStatus] = await Promise.all([
        fetchOutboundAgents(token),
        apiFetchList('/api/leads', token),
        apiFetchList('/api/sessions?limit=20', token),
        apiFetchPublic('/api/system/info'),
        fetchOutboundStatus(token).catch(() => ({})),
      ]);
      setBridgeInfo(obStatus?.bridge || {});
      setAgents(agentList);
      setLeads(leadList);
      setSessions(
        sessionList.filter(
          (s: any) => s.meta?.direction === 'outbound' || s.channel_type === 'outbound',
        ),
      );
      setInfo(sysInfo);
      const paramAgent = searchParams.get('agent_id');
      const paramLead = searchParams.get('lead_id');
      if (agentList.length) {
        const preferred = paramAgent
          ? agentList.find(a => String(a.id) === paramAgent)?.id
          : agentList.find(a => a.slug === 'sales-riley')?.id ?? agentList[0]?.id;
        setAgentId(prev => (prev === '' ? preferred ?? agentList[0].id : prev));
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
  }, [token, searchParams]);

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
      setStatus(
        `Dialing ${res.endpoint}… channel ${res.bridge?.channel_id ?? 'pending'}. ` +
          `Answer on Zoiper extension ${info?.sip_user_1001 || '1001'} on your phone.`,
      );
      setTimeout(() => load(), 3000);
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
        subtitle="Place cold calls from the CRM — your mobile Zoiper (ext 1001) receives the call"
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

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
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

          <GlassCard className="p-6 space-y-4">
            <div className="flex items-center gap-2 text-violet-300">
              <PhoneOutgoing className="w-5 h-5" />
              <h2 className="text-sm font-semibold text-white">2. Place call from CRM</h2>
            </div>

            {agents.length === 0 ? (
              <div className="space-y-3">
                <p className="text-sm text-amber-400/90 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  No outbound agent found. Run <code className="text-xs">make bootstrap</code> to seed Riley, or create an agent with type{' '}
                  <code className="text-xs">outbound_sales</code> under AI Agents.
                </p>
                <Link to="/admin/agents" className="text-xs text-violet-400 hover:underline">
                  Go to AI Agents →
                </Link>
              </div>
            ) : (
              <>
                <label className="block space-y-1.5">
                  <span className="text-xs text-zinc-500 uppercase tracking-wide">Outbound agent</span>
                  <select
                    className={selectCls}
                    value={agentId}
                    onChange={e => setAgentId(e.target.value ? Number(e.target.value) : '')}
                  >
                    {agents.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.slug})
                      </option>
                    ))}
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
                    {leads.map(l => (
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
                  <p className="text-[10px] text-zinc-600">
                    Auto greeting minimizes delay if Gemini is ready fast. Comfort tone avoids dead-air by answering immediately with brief hold audio.
                  </p>
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
                  <p className="text-[10px] text-zinc-600">
                    {isTrunk ? (
                      <>
                        Trunk mode: enter <code className="text-zinc-400">+countrycode…</code> (e.g.{' '}
                        <code className="text-zinc-400">+92335…</code>). Or select a lead with a phone number — leave
                        blank to use the lead&apos;s phone.
                      </>
                    ) : (
                      <>
                        Lab: keep <code className="text-zinc-400">PJSIP/1001</code> when using mobile Zoiper as 1001.
                      </>
                    )}
                  </p>
                </label>

                <div className="flex flex-wrap gap-2">
                  <BtnPrimary
                    onClick={dial}
                    disabled={dialing || !agentId}
                    className="bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500"
                  >
                    {dialing ? 'Originating…' : 'Dial now'}
                  </BtnPrimary>
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
                        setStatus(
                          `Batch: ${res.dialed} ok, ${res.failed} failed — answer both phones.`,
                        );
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
                </div>
                {bridgeInfo.max_concurrent != null && (
                  <p className="text-[10px] text-zinc-600">
                    Bridge capacity: {bridgeInfo.active_calls ?? 0} / {bridgeInfo.max_concurrent} active
                  </p>
                )}
              </>
            )}

            {error && <p className="text-sm text-red-400">{error}</p>}
            {status && <p className="text-sm text-emerald-400/90">{status}</p>}
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
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Manage Riley like inbound agents</h3>
            <p>
              <Link to="/admin/agents" className="text-violet-400 hover:underline">AI Agents</Link> — edit prompt, voice, tools
            </p>
            <p>
              <Link to="/admin/documents" className="text-violet-400 hover:underline">Knowledge base</Link> — upload Trangotech docs for Riley
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
