import { ReactNode } from 'react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';
import { GlassCard } from '@/src/components/admin/theme';

export function DocsSection({
  id,
  title,
  subtitle,
  children,
  className,
}: {
  id: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.section
      id={id}
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-40px' }}
      transition={{ duration: 0.4 }}
      className={cn('scroll-mt-24', className)}
    >
      <div className="mb-4">
        <h2 className="text-xl font-bold text-white">{title}</h2>
        {subtitle && <p className="text-sm text-zinc-400 mt-1">{subtitle}</p>}
      </div>
      {children}
    </motion.section>
  );
}

export function InfoGrid({ items }: { items: { label: string; value: string; mono?: boolean }[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {items.map(item => (
        <GlassCard key={item.label} className="p-4">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">{item.label}</div>
          <div className={cn('text-sm text-zinc-200 mt-1', item.mono && 'font-mono text-xs')}>{item.value}</div>
        </GlassCard>
      ))}
    </div>
  );
}

export function FlowStep({
  step,
  title,
  description,
  icon: Icon,
  delay = 0,
}: {
  step: number;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      whileInView={{ opacity: 1, x: 0 }}
      viewport={{ once: true }}
      transition={{ delay, duration: 0.35 }}
      className="flex gap-4"
    >
      <div className="flex flex-col items-center">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600/30 to-fuchsia-600/20 border border-violet-500/30 flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4 text-violet-300" />
        </div>
        <div className="w-px flex-1 min-h-[24px] bg-gradient-to-b from-violet-500/40 to-transparent mt-2" />
      </div>
      <GlassCard className="flex-1 p-4 mb-4">
        <div className="text-[10px] font-bold text-violet-400 uppercase tracking-wider mb-1">Step {step}</div>
        <div className="text-sm font-semibold text-white">{title}</div>
        <p className="text-xs text-zinc-400 mt-1 leading-relaxed">{description}</p>
      </GlassCard>
    </motion.div>
  );
}

export function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="rounded-xl border border-white/10 bg-black/50 p-4 text-xs font-mono text-zinc-300 overflow-x-auto leading-relaxed whitespace-pre-wrap">
      {children}
    </pre>
  );
}

export function Pill({ children, color = 'violet' }: { children: ReactNode; color?: 'violet' | 'cyan' | 'emerald' | 'amber' }) {
  const colors = {
    violet: 'bg-violet-500/15 text-violet-300 border-violet-500/25',
    cyan: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/25',
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  };
  return (
    <span className={cn('inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border', colors[color])}>
      {children}
    </span>
  );
}
