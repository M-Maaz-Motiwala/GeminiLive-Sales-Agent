import { useState } from 'react';
import { ChevronDown, ChevronRight, Database, Wrench, FileOutput, User, Bot } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GlassCard, Badge } from '@/src/components/admin/theme';

export type TimelineEvent =
  | { type: 'turn'; role: string; text: string; timestamp?: string }
  | {
      type: 'tool';
      name: string;
      label: string;
      params_summary?: string;
      result_summary?: string;
      parameters?: Record<string, unknown>;
      result?: unknown;
      duration_ms?: number;
      timestamp?: string;
    }
  | { type: 'output'; output_type: string; content: unknown; timestamp?: string };

function fmtTime(ts?: string) {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

function TurnBubble({ role, text, agentName, timestamp }: { role: string; text: string; agentName: string; timestamp?: string }) {
  const isUser = role === 'user';
  const label = isUser ? 'Caller' : agentName;

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={cn(
        'shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
        isUser ? 'bg-violet-500/20 text-violet-300' : 'bg-cyan-500/20 text-cyan-300',
      )}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>
      <div className={cn('flex-1 min-w-0 max-w-[85%]', isUser ? 'text-right' : 'text-left')}>
        <div className={cn('flex items-center gap-2 mb-1', isUser ? 'justify-end' : 'justify-start')}>
          <span className="text-xs font-semibold text-zinc-400">{label}</span>
          {timestamp && <span className="text-[10px] text-zinc-600">{fmtTime(timestamp)}</span>}
        </div>
        <div className={cn(
          'rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser
            ? 'bg-gradient-to-br from-violet-600/90 to-fuchsia-600/80 text-white inline-block text-left'
            : 'bg-white/[0.04] border border-white/10 text-zinc-200',
        )}>
          {text}
        </div>
      </div>
    </div>
  );
}

function ToolCard({ event }: { event: Extract<TimelineEvent, { type: 'tool' }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex justify-center py-1">
      <div className="w-full max-w-md">
        <button
          type="button"
          onClick={() => setOpen(v => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-xl border border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10 transition-colors text-left"
        >
          <Wrench className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium text-amber-200/90">{event.label}</div>
            <div className="text-[10px] text-zinc-500 truncate">
              {event.params_summary}
              {event.duration_ms != null && ` · ${event.duration_ms}ms`}
            </div>
          </div>
          {open ? <ChevronDown className="w-3.5 h-3.5 text-zinc-500" /> : <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />}
        </button>
        {open && (
          <div className="mt-1 px-3 py-2 rounded-xl border border-white/5 bg-black/30 text-[10px] font-mono text-zinc-500 overflow-auto max-h-40">
            {event.result_summary && <div className="text-zinc-400 mb-1">{event.result_summary}</div>}
            {event.parameters && Object.keys(event.parameters).length > 0 && (
              <pre className="whitespace-pre-wrap">{JSON.stringify(event.parameters, null, 2)}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function OutputInline({ event }: { event: Extract<TimelineEvent, { type: 'output' }> }) {
  return (
    <div className="flex justify-center py-1">
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 text-xs text-emerald-300/90">
        <FileOutput className="w-3.5 h-3.5" />
        <span>{String(event.output_type).replace(/_/g, ' ')}</span>
        <span className="text-zinc-500">{fmtTime(event.timestamp)}</span>
      </div>
    </div>
  );
}

export function SessionTimeline({ timeline, agentName }: { timeline: TimelineEvent[]; agentName: string }) {
  if (!timeline.length) {
    return (
      <GlassCard className="p-12 text-center">
        <Database className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
        <p className="text-sm text-zinc-500">No conversation yet.</p>
        <p className="text-xs text-zinc-600 mt-1">Transcript appears here as the call progresses.</p>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      {timeline.map((event, i) => {
        if (event.type === 'turn') {
          return (
            <TurnBubble
              key={`turn-${i}`}
              role={event.role}
              text={event.text}
              agentName={agentName}
              timestamp={event.timestamp}
            />
          );
        }
        if (event.type === 'tool') {
          return <ToolCard key={`tool-${i}`} event={event} />;
        }
        if (event.type === 'output') {
          return <OutputInline key={`out-${i}`} event={event} />;
        }
        return null;
      })}
    </div>
  );
}

export function FormattedOutput({ outputType, content }: { outputType: string; content: unknown }) {
  if (!content) return null;
  const c = typeof content === 'string' ? (() => { try { return JSON.parse(content); } catch { return content; } })() : content;

  if (outputType === 'lead_capture' && typeof c === 'object' && c !== null) {
    const o = c as Record<string, string>;
    const fields = ['name', 'email', 'phone', 'company', 'notes'].filter(k => o[k]);
    return (
      <dl className="space-y-2">
        {fields.map(k => (
          <div key={k}>
            <dt className="text-[10px] uppercase tracking-wider text-zinc-500">{k.replace(/_/g, ' ')}</dt>
            <dd className="text-sm text-zinc-300">{o[k]}</dd>
          </div>
        ))}
      </dl>
    );
  }

  if (outputType === 'action_items' && Array.isArray(c)) {
    return (
      <ul className="list-disc list-inside space-y-1 text-sm text-zinc-300">
        {c.map((item, i) => <li key={i}>{typeof item === 'string' ? item : JSON.stringify(item)}</li>)}
      </ul>
    );
  }

  if (typeof c === 'string') {
    return <p className="text-sm text-zinc-300 leading-relaxed">{c}</p>;
  }

  return (
    <pre className="text-xs text-zinc-400 overflow-auto max-h-48 whitespace-pre-wrap font-mono">
      {JSON.stringify(c, null, 2)}
    </pre>
  );
}

export function PreloadedKbCard({ preloaded }: { preloaded: { chunks?: { text: string; score?: number }[]; query?: string } }) {
  const [open, setOpen] = useState(false);
  const chunks = preloaded?.chunks || [];
  if (!chunks.length) return null;

  return (
    <GlassCard className="p-4">
      <button type="button" onClick={() => setOpen(v => !v)} className="w-full flex items-center justify-between text-left">
        <div>
          <div className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Preloaded context</div>
          <div className="text-[10px] text-zinc-600 mt-0.5">{chunks.length} KB chunk{chunks.length !== 1 ? 's' : ''} at call start</div>
        </div>
        {open ? <ChevronDown className="w-4 h-4 text-zinc-500" /> : <ChevronRight className="w-4 h-4 text-zinc-500" />}
      </button>
      {open && (
        <div className="mt-3 space-y-2 border-t border-white/5 pt-3">
          {chunks.map((ch, i) => (
            <p key={i} className="text-xs text-zinc-400 leading-relaxed line-clamp-4">{ch.text}</p>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
