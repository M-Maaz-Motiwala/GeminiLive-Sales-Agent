import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Phone, Radio, Sparkles, Clock } from 'lucide-react';
import { PageHeader, GlassCard, Badge } from '@/src/components/admin/theme';
import { apiFetchList } from '@/src/lib/api';

function statusVariant(s: string): 'live' | 'success' | 'warn' | 'default' {
  if (s === 'active') return 'live';
  if (s === 'ended') return 'success';
  if (s === 'error') return 'warn';
  return 'default';
}

export default function Sessions() {
  const { token } = useAuth();
  const [sessions, setSessions] = useState<any[]>([]);

  useEffect(() => {
    const load = () => apiFetchList('/api/sessions', token).then(setSessions);
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [token]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Sessions"
        subtitle="Call history and live conversations — refreshes every 10s"
        action={
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <Radio className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            Monitoring
          </div>
        }
      />

      <div className="space-y-3">
        {sessions.map(s => {
          const agentName = s.agent?.name?.split('—')[0]?.trim() || s.agent?.name;
          const duration = s.meta?.duration_sec;
          return (
            <Link key={s.id} to={`/admin/sessions/${s.id}`}>
              <GlassCard className="p-4 hover:border-violet-500/30 hover:bg-white/[0.05] transition-all group">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="p-2 rounded-lg bg-violet-500/10 text-violet-300 group-hover:bg-violet-500/20 transition-colors">
                      <Phone className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-white">Session #{s.id}</span>
                        {agentName && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-zinc-400">{agentName}</span>
                        )}
                      </div>
                      <div className="text-xs text-zinc-500 mt-1 truncate">
                        {s.channel_type?.toUpperCase()}
                        {s.caller_id && <> · {s.caller_id}</>}
                        {s.meta?.dialed_extension && <> · ext {s.meta.dialed_extension}</>}
                        {duration != null && <> · {Math.round(duration)}s</>}
                      </div>
                      {s.summary ? (
                        <p className="text-xs text-zinc-400 mt-2 line-clamp-2 leading-relaxed">{s.summary}</p>
                      ) : s.status === 'ended' ? (
                        <p className="text-[10px] text-amber-500/80 mt-2 flex items-center gap-1">
                          <Sparkles className="w-3 h-3" /> Summary pending — open to generate
                        </p>
                      ) : null}
                      {(s.output_types || []).length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {s.output_types.map((t: string) => (
                            <span key={t} className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 uppercase tracking-wide">
                              {t.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <Badge variant={statusVariant(s.status)}>{s.status}</Badge>
                    <span className="text-[10px] text-zinc-600 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(s.started_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              </GlassCard>
            </Link>
          );
        })}
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
