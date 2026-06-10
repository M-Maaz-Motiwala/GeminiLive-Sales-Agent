import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Bot, PhoneCall, UserCheck, FileText, Wifi, Phone, PhoneOutgoing, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiFetchList, apiFetchPublic } from '@/src/lib/api';
import { fetchOutboundAgents } from '@/src/lib/outbound';
import { PageHeader, StatCard, GlassCard, Badge, BtnPrimary } from '@/src/components/admin/theme';

export default function Dashboard() {
  const { token } = useAuth();
  const [stats, setStats] = useState({ sessions: 0, leads: 0, agents: 0, documents: 0, outboundAgents: 0 });
  const [info, setInfo] = useState<any>(null);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      apiFetchList('/api/sessions?limit=100', token),
      apiFetchList('/api/leads?limit=100', token),
      apiFetchList('/api/agents', token),
      apiFetchList('/api/documents', token),
      fetchOutboundAgents(token),
      apiFetchPublic('/api/system/info'),
    ]).then(([sessions, leads, agents, docs, outboundAgents, sysInfo]) => {
      setStats({
        sessions: sessions.length,
        leads: leads.length,
        agents: agents.length,
        documents: docs.length,
        outboundAgents: outboundAgents.length,
      });
      setInfo(sysInfo);
    }).catch(() => {});
  }, [token]);

  const sipServer = info?.sip_server || info?.external_ip || '—';
  const sipPort = info?.sip_port ? `${info.sip_port} ${info?.sip_transport || 'UDP'}` : '5060 UDP';
  const sipUser = info?.sip_username || '1000';
  const sipPass = info?.sip_password || info?.sip_password_hint || '1000pass';
  const sipUser1001 = info?.sip_user_1001 || '1001';
  const sipPass1001 = info?.sip_pass_1001 || '1001pass';
  const sipCodec = info?.sip_codec_label || info?.sip_codec || 'G.711 μ-law (PCMU)';
  const labEndpoint = info?.outbound_lab_endpoint || 'PJSIP/1001';
  const isAutoIp = info?.external_ip_mode === 'auto';
  const testExtensions = info?.test_extensions as Record<string, string> | undefined;

  const inboundExts = testExtensions
    ? Object.entries(testExtensions).filter(([ext]) => ['701', '702', '703', '600'].includes(ext))
    : [
        ['701', 'Maya — Lead intake'],
        ['702', 'Aria — Sales + RAG'],
        ['703', 'Sam — Support FAQ'],
        ['600', 'Echo test (no AI)'],
      ];

  return (
    <div className="p-6 lg:p-10 max-w-6xl">
      <PageHeader
        title="Command Center"
        subtitle="Inbound dial from Zoiper · Outbound dial from CRM (mobile softphone as prospect)"
      />

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <StatCard label="Call sessions" value={stats.sessions} icon={PhoneCall} accent="violet" />
        <StatCard label="Leads captured" value={stats.leads} icon={UserCheck} accent="emerald" />
        <StatCard label="AI agents" value={stats.agents} icon={Bot} accent="cyan" />
        <StatCard label="Outbound agents" value={stats.outboundAgents} icon={PhoneOutgoing} accent="amber" />
        <StatCard label="KB documents" value={stats.documents} icon={FileText} accent="violet" />
      </div>

      {/* Outbound CTA — primary path for cold calls */}
      <GlassCard className="p-6 mb-6 border-orange-500/20 bg-gradient-to-br from-orange-600/10 to-transparent">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <PhoneOutgoing className="w-5 h-5 text-orange-300" />
              <h3 className="text-base font-semibold text-white">Outbound cold calls (Riley)</h3>
              <Badge variant="live">CRM dial</Badge>
            </div>
            <p className="text-sm text-zinc-400 max-w-xl">
              Register your <strong className="text-zinc-200">mobile Zoiper as extension {sipUser1001}</strong> to{' '}
              <span className="font-mono text-orange-300">{sipServer}</span>, then place a call from the CRM — your phone rings as the prospect.
            </p>
            <ol className="mt-3 text-xs text-zinc-500 space-y-1 list-decimal list-inside">
              <li>Mobile Zoiper: user <strong className="text-zinc-400">{sipUser1001}</strong> / pass <strong className="text-zinc-400">{sipPass1001}</strong> @ {sipServer}:{info?.sip_port || 5060}</li>
              <li>Wait for <span className="text-emerald-400">Registered</span> on the phone</li>
              <li>Open <strong className="text-zinc-300">Outbound Calls</strong> → Riley → <strong className="text-zinc-300">Dial now</strong></li>
              <li>Answer on your phone — AI pitches Trangotech and captures the lead</li>
            </ol>
          </div>
          <Link to="/admin/outbound" className="shrink-0">
            <BtnPrimary className="bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500 hover:to-amber-500 shadow-orange-900/30">
              <PhoneOutgoing className="w-4 h-4" />
              Open Outbound Calls
              <ArrowRight className="w-4 h-4" />
            </BtnPrimary>
          </Link>
        </div>
      </GlassCard>

      <div className="grid lg:grid-cols-2 gap-6">
        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Wifi className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">SIP — inbound (extension 1000)</h3>
            <Badge variant="live">LAN</Badge>
          </div>
          <p className="text-[10px] text-zinc-500 mb-3">
            {isAutoIp
              ? 'SIP server IP is auto-detected on each ./start.sh — value below is current.'
              : 'SIP server IP is fixed in .env (EXTERNAL_IP).'}
          </p>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between items-center border-b border-white/[0.04] pb-2">
              <dt className="text-zinc-500">SIP server</dt>
              <dd className="font-mono text-violet-300 font-medium text-right flex items-center gap-2">
                {sipServer}
                {isAutoIp && sipServer !== '—' && <Badge variant="live">auto</Badge>}
              </dd>
            </div>
            {[
              ['Port', sipPort],
              ['Username', sipUser],
              ['Password', sipPass],
              ['Codec', sipCodec],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-white/[0.04] pb-2">
                <dt className="text-zinc-500">{k}</dt>
                <dd className="font-mono text-violet-300 font-medium">{v}</dd>
              </div>
            ))}
          </dl>
        </GlassCard>

        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <PhoneOutgoing className="w-4 h-4 text-orange-400" />
            <h3 className="text-sm font-semibold text-white">SIP — outbound prospect ({sipUser1001})</h3>
          </div>
          <p className="text-[10px] text-zinc-500 mb-3">
            Use a second Zoiper (mobile) to receive CRM-originated calls. Default dial target:{' '}
            <code className="text-orange-300">{labEndpoint}</code>
          </p>
          <dl className="space-y-3 text-sm">
            {[
              ['SIP server', sipServer],
              ['Port', sipPort],
              ['Username', sipUser1001],
              ['Password', sipPass1001],
              ['Codec', sipCodec],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-white/[0.04] pb-2">
                <dt className="text-zinc-500">{k}</dt>
                <dd className="font-mono text-orange-300/90 font-medium text-right">{v}</dd>
              </div>
            ))}
          </dl>
          <Link to="/admin/outbound" className="inline-flex items-center gap-1 mt-4 text-xs text-orange-400 hover:text-orange-300">
            Dial from CRM <ArrowRight className="w-3 h-3" />
          </Link>
        </GlassCard>

        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Phone className="w-4 h-4 text-fuchsia-400" />
            <h3 className="text-sm font-semibold text-white">Inbound agent extensions</h3>
          </div>
          <div className="space-y-2">
            {inboundExts.map(([ext, name]) => (
              <div key={ext} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <span className="font-mono text-lg font-bold text-violet-400 w-12">{ext}</span>
                <span className="text-sm text-zinc-400">{name}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <PhoneOutgoing className="w-4 h-4 text-orange-400" />
            <h3 className="text-sm font-semibold text-white">Outbound agent</h3>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 p-3 rounded-xl bg-orange-500/5 border border-orange-500/20">
              <span className="font-mono text-lg font-bold text-orange-400 w-12">CRM</span>
              <span className="text-sm text-zinc-400">Riley — Cold Outbound (dial from Outbound Calls, not an extension)</span>
            </div>
            {testExtensions?.['704'] && (
              <div className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <span className="font-mono text-lg font-bold text-violet-400 w-12">704</span>
                <span className="text-sm text-zinc-400">{testExtensions['704']} (optional inbound test)</span>
              </div>
            )}
          </div>
        </GlassCard>

        <GlassCard className="p-6 lg:col-span-2">
          <h3 className="text-sm font-semibold text-white mb-4">Quick start checklist</h3>
          <ol className="grid sm:grid-cols-2 gap-3 text-sm text-zinc-400">
            {[
              <>Register mobile Zoiper as <strong className="text-white">{sipUser1001}</strong> @ {sipServer}</>,
              <><Link to="/admin/outbound" className="text-orange-400 hover:text-orange-300">Outbound Calls</Link> → Riley → Dial now → answer on phone</>,
              <><Link to="/admin/agents" className="text-violet-400 hover:text-violet-300">Agents</Link> — edit prompts, tools, outbound_sales type</>,
              <><Link to="/admin/documents" className="text-violet-400 hover:text-violet-300">Knowledge base</Link> — upload docs per agent</>,
              <>Inbound: dial <strong className="text-white">701</strong> from Zoiper 1000 — check <Link to="/admin/sessions" className="text-violet-400">Sessions</Link></>,
              <><Link to="/admin/leads" className="text-violet-400 hover:text-violet-300">Leads</Link> — use Call button to dial with CRM context</>,
            ].map((step, i) => (
              <li key={i} className="flex gap-3 p-3 rounded-xl bg-black/30 border border-white/[0.04]">
                <span className="shrink-0 w-6 h-6 rounded-full bg-violet-600/30 text-violet-300 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </GlassCard>
      </div>
    </div>
  );
}
