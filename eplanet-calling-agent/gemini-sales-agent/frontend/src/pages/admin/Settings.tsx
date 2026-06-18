import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetchPublic } from '@/src/lib/api';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';

export default function Settings() {
  const { token } = useAuth();
  const [sipInfo, setSipInfo] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    apiFetchPublic<Record<string, string>>('/api/system/info')
      .then(d => { setSipInfo(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [token]);

  return (
    <div className="p-6 lg:p-10 space-y-6">
      <PageHeader
        title="Platform Settings"
        subtitle="Create organizations to register DIDs — agents and KB are scoped per organization"
      />

      <GlassCard className="p-6 space-y-3">
        <h2 className="text-sm font-semibold text-white">Telephony</h2>
        <p className="text-xs text-zinc-500">
          New DIDs are written to <code className="text-zinc-400">asterisk/generated/org-dids.conf</code> when you
          create an organization. Point the number at your Asterisk trunk in DIDWW — no manual dialplan edits needed.
        </p>
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
          </dl>
        )}
      </GlassCard>
    </div>
  );
}
