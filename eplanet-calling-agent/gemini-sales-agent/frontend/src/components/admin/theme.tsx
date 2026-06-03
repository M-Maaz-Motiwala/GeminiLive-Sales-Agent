import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-violet-400/80 mb-1">Call Center AI</p>
        <h1 className="text-3xl font-bold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="text-sm text-zinc-400 mt-1">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function GlassCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn(
      'rounded-2xl border border-white/[0.08] bg-white/[0.03] backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.4)]',
      className,
    )}>
      {children}
    </div>
  );
}

export function StatCard({ label, value, icon: Icon, accent = 'violet' }: {
  label: string; value: number | string; icon: any; accent?: 'violet' | 'cyan' | 'emerald' | 'amber';
}) {
  const gradients = {
    violet: 'from-violet-600/20 to-fuchsia-600/5 border-violet-500/20',
    cyan: 'from-cyan-600/20 to-blue-600/5 border-cyan-500/20',
    emerald: 'from-emerald-600/20 to-teal-600/5 border-emerald-500/20',
    amber: 'from-amber-600/20 to-orange-600/5 border-amber-500/20',
  };
  const iconBg = {
    violet: 'bg-violet-500/20 text-violet-300',
    cyan: 'bg-cyan-500/20 text-cyan-300',
    emerald: 'bg-emerald-500/20 text-emerald-300',
    amber: 'bg-amber-500/20 text-amber-300',
  };
  return (
    <div className={cn('rounded-2xl border bg-gradient-to-br p-5 flex items-center gap-4', gradients[accent])}>
      <div className={cn('p-3 rounded-xl', iconBg[accent])}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <div className="text-2xl font-bold text-white tabular-nums">{value}</div>
        <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</div>
      </div>
    </div>
  );
}

export function BtnPrimary({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold',
        'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white',
        'hover:from-violet-500 hover:to-fuchsia-500 shadow-lg shadow-violet-900/40',
        'disabled:opacity-50 transition-all',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function BtnGhost({ children, className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        'inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium',
        'text-zinc-300 border border-white/10 hover:bg-white/5 transition-colors',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function InputField({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return (
    <div>
      {label && <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">{label}</label>}
      <input
        className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500/50"
        {...props}
      />
    </div>
  );
}

export function Badge({ children, variant = 'default' }: { children: ReactNode; variant?: 'default' | 'success' | 'warn' | 'live' }) {
  const styles = {
    default: 'bg-zinc-800 text-zinc-300 border-zinc-700',
    success: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    warn: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    live: 'bg-red-500/15 text-red-400 border-red-500/30 animate-pulse',
  };
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide border', styles[variant])}>
      {children}
    </span>
  );
}
