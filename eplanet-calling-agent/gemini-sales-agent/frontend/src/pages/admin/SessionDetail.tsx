import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { ArrowLeft, Zap, Loader2, Clock, Phone, BarChart3 } from 'lucide-react';
import { PageHeader, GlassCard, BtnGhost, Badge, StatCard } from '@/src/components/admin/theme';
import {
  SessionTimeline,
  FormattedOutput,
  PreloadedKbCard,
  type TimelineEvent,
} from '@/src/components/admin/SessionTimeline';
import { API_BASE, apiFetch } from '@/src/lib/api';

export default function SessionDetail() {
  const { id } = useParams();
  const { token } = useAuth();
  const [session, setSession] = useState<any | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = () => {
    apiFetch(`/api/sessions/${id}`, token).then(setSession).catch(() => setSession(null));
  };

  useEffect(() => {
    load();
    const ms = session?.status === 'active' ? 3000 : 8000;
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, token, session?.status]);

  const isLive = session?.status === 'active';

  const summarize = async () => {
    setSummarizing(true);
    const res = await fetch(`${API_BASE}/api/sessions/${id}/summarize`, { method: 'POST', headers });
    const data = await res.json();
    setSession((s: any) => ({ ...s, summary: data.summary }));
    setSummarizing(false);
  };

  if (!session) {
    return (
      <div className="p-8 flex items-center gap-2 text-zinc-500">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading session…
      </div>
    );
  }

  const agentName = session.agent?.name?.split('—')[0]?.trim() || session.agent?.name || 'Agent';
  const duration = session.meta?.duration_sec;
  const dialedExt = session.meta?.dialed_extension;
  const bridgeStats = session.meta?.bridge_stats || {};
  const timeline: TimelineEvent[] = session.timeline || [];
  const turnCount = (session.turns || []).length;

  const subtitleParts = [
    session.channel_type?.toUpperCase(),
    agentName,
    dialedExt && `ext ${dialedExt}`,
    session.caller_id && `caller ${session.caller_id}`,
    duration != null && `${Math.round(duration)}s`,
    new Date(session.started_at).toLocaleString(),
  ].filter(Boolean);

  return (
    <div className="p-6 lg:p-8">
      <Link to="/admin/sessions" className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-violet-400 mb-6 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to sessions
      </Link>

      <PageHeader
        title={`Session #${id}`}
        subtitle={subtitleParts.join(' · ')}
        action={
          <div className="flex items-center gap-2">
            {isLive && <Badge variant="live">Live</Badge>}
            <BtnGhost onClick={summarize} disabled={summarizing}>
              {summarizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
              {summarizing ? 'Generating…' : 'Re-summarize'}
            </BtnGhost>
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-4 order-2 lg:order-1">
          {session.summary && (
            <GlassCard className="p-5 border-violet-500/20 bg-gradient-to-br from-violet-600/10 to-transparent">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-violet-400 mb-2">
                Call summary {session.ended_at ? '(auto-generated)' : ''}
              </div>
              <p className="text-sm text-zinc-300 leading-relaxed">{session.summary}</p>
            </GlassCard>
          )}

          {!session.summary && session.status === 'ended' && (
            <GlassCard className="p-4 text-xs text-zinc-500">Summary generating… refresh shortly.</GlassCard>
          )}

          {(session.outputs || []).length > 0 && (
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 px-1">Key outputs</h3>
              {(session.outputs || []).map((o: any) => (
                <GlassCard key={o.id} className="p-4">
                  <Badge variant="success">{String(o.output_type).replace(/_/g, ' ')}</Badge>
                  <FormattedOutput outputType={String(o.output_type)} content={o.content} />
                </GlassCard>
              ))}
            </div>
          )}

          {session.meta?.preloaded_kb && (
            <PreloadedKbCard preloaded={session.meta.preloaded_kb} />
          )}

          <div className="grid grid-cols-2 gap-3">
            <StatCard label="Turns" value={turnCount} icon={Phone} accent="violet" />
            <StatCard
              label="Duration"
              value={duration != null ? `${Math.round(duration)}s` : isLive ? '…' : '—'}
              icon={Clock}
              accent="cyan"
            />
          </div>

          {(bridgeStats.gemini_turns != null || bridgeStats.interruptions != null) && (
            <GlassCard className="p-4">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3">
                <BarChart3 className="w-3.5 h-3.5" /> Call stats
              </div>
              <dl className="space-y-1.5 text-xs text-zinc-400">
                {bridgeStats.gemini_turns != null && (
                  <div className="flex justify-between"><dt>Model turns</dt><dd className="text-zinc-300">{bridgeStats.gemini_turns}</dd></div>
                )}
                {bridgeStats.interruptions != null && (
                  <div className="flex justify-between"><dt>Interruptions</dt><dd className="text-zinc-300">{bridgeStats.interruptions}</dd></div>
                )}
                {bridgeStats.rtp_in != null && (
                  <div className="flex justify-between"><dt>RTP in</dt><dd className="text-zinc-300">{bridgeStats.rtp_in}</dd></div>
                )}
              </dl>
            </GlassCard>
          )}
        </div>

        {/* Conversation */}
        <div className="lg:col-span-2 order-1 lg:order-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Conversation</h3>
            {isLive && (
              <span className="text-[10px] text-emerald-400/80 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Updating every 3s
              </span>
            )}
          </div>
          <SessionTimeline timeline={timeline} agentName={agentName} />
        </div>
      </div>
    </div>
  );
}
