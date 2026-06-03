import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Bot, PhoneCall, UserCheck, FileText, Wifi, Phone } from 'lucide-react';
import { Link } from 'react-router-dom';
import { apiFetchList, apiFetchPublic } from '@/src/lib/api';
import { PageHeader, StatCard, GlassCard, Badge } from '@/src/components/admin/theme';

export default function Dashboard() {
  const { token } = useAuth();
  const [stats, setStats] = useState({ sessions: 0, leads: 0, agents: 0, documents: 0 });
  const [info, setInfo] = useState<any>(null);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      apiFetchList('/api/sessions?limit=100', token),
      apiFetchList('/api/leads?limit=100', token),
      apiFetchList('/api/agents', token),
      apiFetchList('/api/documents', token),
      apiFetchPublic('/api/system/info'),
    ]).then(([sessions, leads, agents, docs, sysInfo]) => {
      setStats({
        sessions: sessions.length,
        leads: leads.length,
        agents: agents.length,
        documents: docs.length,
      });
      setInfo(sysInfo);
    }).catch(() => {});
  }, [token]);

  const sipServer = info?.sip_server || '—';

  return (
    <div className="p-6 lg:p-10 max-w-6xl">
      <PageHeader
        title="Command Center"
        subtitle="Monitor agents, calls, and knowledge base — dial from Zoiper on your LAN"
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard label="Call sessions" value={stats.sessions} icon={PhoneCall} accent="violet" />
        <StatCard label="Leads captured" value={stats.leads} icon={UserCheck} accent="emerald" />
        <StatCard label="AI agents" value={stats.agents} icon={Bot} accent="cyan" />
        <StatCard label="KB documents" value={stats.documents} icon={FileText} accent="amber" />
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <GlassCard className="p-6">
          <div className="flex items-center gap-2 mb-4">
            <Wifi className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">SIP phone setup (Zoiper)</h3>
            <Badge variant="live">LAN</Badge>
          </div>
          <dl className="space-y-3 text-sm">
            {[
              ['SIP server', sipServer],
              ['Port', '5060 UDP'],
              ['Username', '1000'],
              ['Password', '1000pass'],
              ['Codec', 'G.711 μ-law (PCMU)'],
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
            <Phone className="w-4 h-4 text-fuchsia-400" />
            <h3 className="text-sm font-semibold text-white">Agent extensions</h3>
          </div>
          <div className="space-y-2">
            {[
              ['701', 'Maya — Lead intake'],
              ['702', 'Aria — Sales + RAG'],
              ['703', 'Sam — Support FAQ'],
              ['600', 'Echo test (no AI)'],
            ].map(([ext, name]) => (
              <div key={ext} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <span className="font-mono text-lg font-bold text-violet-400 w-12">{ext}</span>
                <span className="text-sm text-zinc-400">{name}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard className="p-6 lg:col-span-2">
          <h3 className="text-sm font-semibold text-white mb-4">Quick start checklist</h3>
          <ol className="grid sm:grid-cols-2 gap-3 text-sm text-zinc-400">
            {[
              <>Configure Zoiper with SIP server above, register on same Wi‑Fi</>,
              <><Link to="/admin/agents" className="text-violet-400 hover:text-violet-300">Agents</Link> — edit personas, extensions, tools</>,
              <><Link to="/admin/documents" className="text-violet-400 hover:text-violet-300">Knowledge base</Link> — upload PDFs, wait for indexed</>,
              <>Dial <strong className="text-white">701</strong> and speak — check <Link to="/admin/sessions" className="text-violet-400">Sessions</Link></>,
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
