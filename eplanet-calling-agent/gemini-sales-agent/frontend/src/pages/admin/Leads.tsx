import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Users } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';
import { API_BASE } from '@/src/lib/api';

const STATUSES = ['new', 'qualified', 'contacted', 'closed', 'lost'];

const selectCls = 'rounded-full border border-white/10 bg-black/40 px-3 py-1 text-[10px] font-semibold uppercase text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 cursor-pointer';

export default function Leads() {
  const { token } = useAuth();
  const [leads, setLeads] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = (status = '') => {
    const q = status ? `?status=${status}` : '';
    fetch(`${API_BASE}/api/leads${q}`, { headers }).then(r => r.json()).then(setLeads).catch(() => {});
  };

  useEffect(() => { load(statusFilter); }, [token, statusFilter]);

  const updateStatus = async (id: number, status: string) => {
    await fetch(`${API_BASE}/api/leads/${id}`, { method: 'PUT', headers, body: JSON.stringify({ status }) });
    load(statusFilter);
  };

  return (
    <div className="p-6 lg:p-8">
      <PageHeader title="Leads" subtitle="CRM lead tracking from agent conversations" />

      <div className="flex flex-wrap gap-2 mb-6">
        <FilterBtn active={statusFilter === ''} onClick={() => setStatusFilter('')}>All</FilterBtn>
        {STATUSES.map(s => (
          <FilterBtn key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>{s}</FilterBtn>
        ))}
      </div>

      <div className="space-y-3">
        {leads.map(l => (
          <GlassCard key={l.id} className="p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-300">
                <Users className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-white">{l.name || '(no name)'}</div>
                <div className="text-xs text-zinc-500 truncate">{l.email} · {l.phone} · {l.company}</div>
              </div>
            </div>
            <select value={l.status} onChange={e => updateStatus(l.id, e.target.value)} className={selectCls}>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </GlassCard>
        ))}
        {leads.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">No leads found.</GlassCard>
        )}
      </div>
    </div>
  );
}

function FilterBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-3 py-1.5 rounded-xl text-[10px] font-semibold uppercase tracking-wide transition-all',
        active
          ? 'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white shadow-lg shadow-violet-900/30'
          : 'border border-white/10 text-zinc-400 hover:bg-white/5',
      )}
    >
      {children}
    </button>
  );
}
