import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import {
  ArrowLeft, Zap, Loader2, Clock, Phone, BarChart3,
  FileOutput, RefreshCw, Users, AlertCircle,
} from 'lucide-react';
import { PageHeader, GlassCard, BtnGhost, Badge, StatCard } from '@/src/components/admin/theme';
import {
  SessionTimeline,
  FormattedOutput,
  PreloadedKbCard,
  StructuredSummaryCard,
  type TimelineEvent,
} from '@/src/components/admin/SessionTimeline';
import { API_BASE, apiFetch } from '@/src/lib/api';

const OUTPUT_OPTIONS = [
  { value: 'summary', label: 'Structured summary' },
  { value: 'lead_capture', label: 'Lead capture' },
  { value: 'action_items', label: 'Action items' },
];

export default function SessionDetail() {
  const { id } = useParams();
  const { token } = useAuth();
  const [session, setSession] = useState<any | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [generatingOutput, setGeneratingOutput] = useState(false);
  const [runningPostCall, setRunningPostCall] = useState(false);
  const [outputType, setOutputType] = useState('summary');
  const [error, setError] = useState('');
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
  const turnCount = (session?.turns || []).length;
  const canSummarize = turnCount > 0;

  const summarize = async () => {
    setSummarizing(true);
    setError('');
    try {
      const data = await apiFetch<{ summary: string }>(`/api/sessions/${id}/summarize`, token, { method: 'POST' });
      setSession((s: any) => ({ ...s, summary: data.summary }));
    } catch (e: any) {
      setError(e.message || 'Summary failed');
    } finally {
      setSummarizing(false);
    }
  };

  const generateOutput = async () => {
    setGeneratingOutput(true);
    setError('');
    try {
      await apiFetch(`/api/sessions/${id}/outputs?output_type=${outputType}`, token, { method: 'POST' });
      load();
    } catch (e: any) {
      setError(e.message || 'Output generation failed');
    } finally {
      setGeneratingOutput(false);
    }
  };

  const runPostCall = async () => {
    setRunningPostCall(true);
    setError('');
    try {
      await apiFetch(`/api/sessions/${id}/post-call`, token, {
        method: 'POST',
        body: JSON.stringify({ force: true }),
      });
      setTimeout(load, 2500);
      setTimeout(load, 6000);
    } catch (e: any) {
      setError(e.message || 'Post-call processing failed');
    } finally {
      setRunningPostCall(false);
    }
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
  const tokenUsage = session.meta?.token_usage;
  const ragMetrics = session.meta?.rag_metrics;
  const postCall = session.meta?.post_call;
  const timeline: TimelineEvent[] = session.timeline || [];
  const summaryOutput = (session.outputs || []).find((o: any) => o.output_type === 'summary');
  const leadOutput = (session.outputs || []).find((o: any) => o.output_type === 'lead_capture');

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
          <div className="flex flex-wrap items-center gap-2">
            {isLive && <Badge variant="live">Live</Badge>}
            <BtnGhost onClick={summarize} disabled={summarizing || !canSummarize}>
              {summarizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
              {summarizing ? 'Generating…' : isLive ? 'Summarize now' : 'Re-summarize'}
            </BtnGhost>
            {!isLive && !session.summary && (
              <BtnGhost onClick={runPostCall} disabled={runningPostCall || !canSummarize}>
                {runningPostCall ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                Generate all
              </BtnGhost>
            )}
          </div>
        }
      />

      {error && (
        <GlassCard className="p-4 mb-4 border-red-500/30 bg-red-500/5 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{error}</p>
        </GlassCard>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-4 order-2 lg:order-1">
          {session.summary && (
            <GlassCard className="p-5 border-violet-500/20 bg-gradient-to-br from-violet-600/10 to-transparent">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-violet-400 mb-2">
                Call overview {session.ended_at && !isLive ? '(auto at end)' : isLive ? '(live)' : ''}
              </div>
              <p className="text-sm text-zinc-300 leading-relaxed">{session.summary}</p>
            </GlassCard>
          )}

          {!session.summary && session.status === 'ended' && canSummarize && (
            <GlassCard className="p-4 text-xs text-zinc-500">
              {postCall?.status === 'running' || runningPostCall
                ? 'Generating summary and outputs…'
                : postCall?.errors?.length
                  ? `Summary failed: ${postCall.errors[0]}`
                  : 'Summary not generated yet. Click Generate all or Summarize now.'}
            </GlassCard>
          )}

          {summaryOutput && (
            <GlassCard className="p-5 border-cyan-500/20">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-cyan-400 mb-3">
                Structured overview
              </div>
              <StructuredSummaryCard content={summaryOutput.content} />
            </GlassCard>
          )}

          {leadOutput && (
            <GlassCard className="p-5 border-emerald-500/20">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-emerald-400 mb-3">
                <Users className="w-3.5 h-3.5" /> Lead capture
              </div>
              <FormattedOutput outputType="lead_capture" content={leadOutput.content} />
              {postCall?.lead_id && (
                <Link to="/admin/leads" className="text-xs text-violet-400 hover:underline mt-3 inline-block">
                  View in Leads →
                </Link>
              )}
            </GlassCard>
          )}

          {(session.outputs || []).filter((o: any) => !['summary', 'lead_capture'].includes(o.output_type)).length > 0 && (
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500 px-1">Other outputs</h3>
              {(session.outputs || [])
                .filter((o: any) => !['summary', 'lead_capture'].includes(o.output_type))
                .map((o: any) => (
                  <GlassCard key={o.id} className="p-4">
                    <Badge variant="success">{String(o.output_type).replace(/_/g, ' ')}</Badge>
                    <div className="mt-3">
                      <FormattedOutput outputType={String(o.output_type)} content={o.content} />
                    </div>
                  </GlassCard>
                ))}
            </div>
          )}

          <GlassCard className="p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-3 flex items-center gap-2">
              <FileOutput className="w-3.5 h-3.5" /> Generate output
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                value={outputType}
                onChange={e => setOutputType(e.target.value)}
                className="flex-1 min-w-[140px] rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white"
              >
                {OUTPUT_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <BtnGhost onClick={generateOutput} disabled={generatingOutput || !canSummarize}>
                {generatingOutput ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Run'}
              </BtnGhost>
            </div>
          </GlassCard>

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

          {tokenUsage && (
            <GlassCard className="p-4 border-amber-500/20">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-400 mb-3">
                <BarChart3 className="w-3.5 h-3.5" /> Token usage (est.)
              </div>
              <dl className="space-y-1.5 text-xs text-zinc-400">
                <div className="flex justify-between">
                  <dt>Audio input (user)</dt>
                  <dd className="text-zinc-300">{tokenUsage.audio_input_tokens?.toLocaleString()} tok</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Text context (prompt/tools)</dt>
                  <dd className="text-zinc-300">{tokenUsage.text_input_context_tokens?.toLocaleString()} tok</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Audio output (agent)</dt>
                  <dd className="text-zinc-300">{tokenUsage.audio_output_tokens?.toLocaleString()} tok</dd>
                </div>
                {tokenUsage.text_output_tokens > 0 && (
                  <div className="flex justify-between">
                    <dt>Transcription output</dt>
                    <dd className="text-zinc-300">{tokenUsage.text_output_tokens?.toLocaleString()} tok</dd>
                  </div>
                )}
                <div className="flex justify-between border-t border-white/5 pt-2 mt-2">
                  <dt className="text-zinc-300">Total estimated</dt>
                  <dd className="text-amber-300 font-medium">{tokenUsage.estimated_total_tokens?.toLocaleString()} tok</dd>
                </div>
                {tokenUsage.pricing_estimate_usd?.total_usd != null && (
                  <div className="flex justify-between">
                    <dt>Est. cost</dt>
                    <dd className="text-emerald-300">${tokenUsage.pricing_estimate_usd.total_usd.toFixed(4)}</dd>
                  </div>
                )}
                {(tokenUsage.audio_input_sec != null || tokenUsage.audio_output_sec != null) && (
                  <div className="text-[10px] text-zinc-600 pt-1">
                    Audio: {tokenUsage.audio_input_sec ?? 0}s in · {tokenUsage.audio_output_sec ?? 0}s out
                  </div>
                )}
              </dl>
            </GlassCard>
          )}

          {ragMetrics && ragMetrics.query_count > 0 && (
            <GlassCard className="p-4 border-cyan-500/20">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-cyan-400 mb-3">
                <BarChart3 className="w-3.5 h-3.5" /> RAG metrics
              </div>
              <dl className="space-y-1.5 text-xs text-zinc-400">
                <div className="flex justify-between"><dt>Queries</dt><dd className="text-zinc-300">{ragMetrics.query_count}</dd></div>
                <div className="flex justify-between"><dt>Avg top score</dt><dd className="text-zinc-300">{ragMetrics.avg_top_score}</dd></div>
                <div className="flex justify-between"><dt>Avg latency</dt><dd className="text-zinc-300">{ragMetrics.avg_latency_ms} ms</dd></div>
                <div className="flex justify-between"><dt>High relevance</dt><dd className="text-emerald-300">{ragMetrics.high_relevance_queries}</dd></div>
                <div className="flex justify-between"><dt>No results</dt><dd className="text-zinc-300">{ragMetrics.no_result_queries}</dd></div>
              </dl>
            </GlassCard>
          )}

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
