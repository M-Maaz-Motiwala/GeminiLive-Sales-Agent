import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetchPublic, apiFetchList } from '@/src/lib/api';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';

export default function Settings() {
  const { token } = useAuth();
  const [sipInfo, setSipInfo] = useState<Record<string, string>>({});
  const [dids, setDids] = useState<{ did: string; agent_count: number }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      apiFetchPublic<Record<string, string>>('/api/system/info'),
      apiFetchList<{ did: string; agent_count: number }>('/api/agents/dids', token),
    ])
      .then(([info, didList]) => {
        setSipInfo(info);
        setDids(didList);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [token]);

  return (
    <div className="p-6 lg:p-10 space-y-6">
      <PageHeader
        title="Platform Settings"
        subtitle="Each DID is an organization — multiple sales agents per DID handle inbound and outbound"
      />

      <GlassCard className="p-6 space-y-3">
        <h2 className="text-sm font-semibold text-white">Registered organization DIDs</h2>
        <p className="text-xs text-zinc-500">
          Create agents with a DID in the CRM to register a new organization. Inbound calls to that number
          route to the agent pool automatically — no Asterisk dialplan changes needed.
        </p>
        {loading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : dids.length === 0 ? (
          <p className="text-sm text-zinc-500">No DIDs registered yet.</p>
        ) : (
          <ul className="text-sm text-zinc-400 space-y-1">
            {dids.map(d => (
              <li key={d.did}>{d.did} — {d.agent_count} active agent{d.agent_count !== 1 ? 's' : ''}</li>
            ))}
          </ul>
        )}
      </GlassCard>

      <GlassCard className="p-6 space-y-3">
        <h2 className="text-sm font-semibold text-white">Telephony</h2>
        {loading ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : (
          <dl className="text-sm text-zinc-400 space-y-2">
            {sipInfo.sip_server && (
              <div className="flex gap-2"><dt className="text-zinc-500 w-28">SIP server</dt><dd>{sipInfo.sip_server}</dd></div>
            )}
            {sipInfo.sip_port && (
              <div className="flex gap-2"><dt className="text-zinc-500 w-28">SIP port</dt><dd>{sipInfo.sip_port}</dd></div>
            )}
            {sipInfo.sip_codec_label && (
              <div className="flex gap-2"><dt className="text-zinc-500 w-28">Codec</dt><dd>{sipInfo.sip_codec_label}</dd></div>
            )}
          </dl>
        )}
      </GlassCard>
    </div>
  );
}
