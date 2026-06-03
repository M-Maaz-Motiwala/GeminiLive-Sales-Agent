import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { PageHeader, GlassCard, Badge } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';

const OUTPUT_TYPES = ['', 'lead_capture', 'action_items', 'research_report', 'code_analysis', 'summary'];
const selectCls = 'rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Outputs() {
  const { token } = useAuth();
  const [outputs, setOutputs] = useState<any[]>([]);
  const [typeFilter, setTypeFilter] = useState('');
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    const q = typeFilter ? `?output_type=${typeFilter}` : '';
    apiFetchList(`/api/outputs${q}`, token).then(setOutputs);
  }, [token, typeFilter]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Outputs"
        subtitle="Structured outputs from agent sessions"
        action={
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className={selectCls}>
            <option value="">All types</option>
            {OUTPUT_TYPES.filter(Boolean).map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        }
      />

      <div className="space-y-3">
        {outputs.map(o => (
          <GlassCard key={o.id} className="p-4">
            <div className="flex flex-wrap items-center gap-3 mb-3">
              <Badge variant="success">{o.output_type}</Badge>
              <span className="text-xs text-zinc-500">Session #{o.session_id}</span>
              <span className="text-[10px] text-zinc-600">{new Date(o.created_at).toLocaleString()}</span>
            </div>
            <pre className="text-xs text-zinc-400 overflow-auto max-h-48 whitespace-pre-wrap font-mono">
              {typeof o.content === 'string' ? o.content : JSON.stringify(o.content, null, 2)}
            </pre>
          </GlassCard>
        ))}
        {outputs.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">No outputs yet.</GlassCard>
        )}
      </div>
    </div>
  );
}
