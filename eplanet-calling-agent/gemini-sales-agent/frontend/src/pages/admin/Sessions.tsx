import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Phone, Radio } from 'lucide-react';
import { PageHeader, GlassCard, Badge } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';

function statusVariant(s: string): 'live' | 'success' | 'warn' | 'default' {
  if (s === 'active') return 'live';
  if (s === 'ended') return 'success';
  if (s === 'error') return 'warn';
  return 'default';
}

export default function Sessions() {
  const { token } = useAuth();
  const [sessions, setSessions] = useState<any[]>([]);
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    const load = () => apiFetchList('/api/sessions', token).then(setSessions);
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [token]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Live Sessions"
        subtitle="SIP call history — auto-refreshes every 10s"
        action={
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <Radio className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            Monitoring
          </div>
        }
      />

      <div className="space-y-3">
        {sessions.map(s => (
          <Link key={s.id} to={`/admin/sessions/${s.id}`}>
            <GlassCard className="p-4 hover:border-violet-500/30 hover:bg-white/[0.05] transition-all group">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="p-2 rounded-lg bg-violet-500/10 text-violet-300 group-hover:bg-violet-500/20 transition-colors">
                    <Phone className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white">Session #{s.id}</div>
                    <div className="text-xs text-zinc-500 truncate">
                      {s.channel_type} · agent {s.agent_id}
                      {s.caller_id && <> · {s.caller_id}</>}
                    </div>
                  </div>
                </div>
                <Badge variant={statusVariant(s.status)}>{s.status}</Badge>
              </div>
              {s.summary && <p className="text-xs text-zinc-400 mt-2 line-clamp-2">{s.summary}</p>}
              <p className="text-[10px] text-zinc-600 mt-2">{new Date(s.started_at).toLocaleString()}</p>
            </GlassCard>
          </Link>
        ))}
        {sessions.length === 0 && (
          <GlassCard className="p-12 text-center">
            <Phone className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
            <p className="text-sm text-zinc-500">No sessions yet. Dial 701, 702, or 703 from Zoiper.</p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}
