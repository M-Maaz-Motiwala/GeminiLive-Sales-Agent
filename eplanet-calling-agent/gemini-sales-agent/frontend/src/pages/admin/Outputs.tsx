import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { PageHeader, GlassCard, Badge } from '@/src/components/admin/theme';
import { FormattedOutput } from '@/src/components/admin/SessionTimeline';
import { apiFetchList } from '@/src/lib/api';

const OUTPUT_TYPES = ['', 'summary', 'lead_capture', 'action_items', 'research_report', 'code_analysis'];
const selectCls = 'rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Outputs() {
  const { token } = useAuth();
  const [outputs, setOutputs] = useState<any[]>([]);
  const [typeFilter, setTypeFilter] = useState('');

  useEffect(() => {
    const q = typeFilter ? `?output_type=${typeFilter}` : '';
    apiFetchList(`/api/outputs${q}`, token).then(setOutputs);
  }, [token, typeFilter]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Outputs"
        subtitle="Structured AI artifacts from calls — lead capture, action items, summaries"
        action={
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)} className={selectCls}>
            <option value="">All types</option>
            {OUTPUT_TYPES.filter(Boolean).map(t => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
        }
      />

      <div className="space-y-4">
        {outputs.map(o => (
          <GlassCard key={o.id} className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="success">{String(o.output_type).replace(/_/g, ' ')}</Badge>
                <Link
                  to={`/admin/sessions/${o.session_id}`}
                  className="text-xs text-violet-400 hover:underline"
                >
                  Session #{o.session_id}
                </Link>
              </div>
              <span className="text-[10px] text-zinc-600">{new Date(o.created_at).toLocaleString()}</span>
            </div>
            <FormattedOutput outputType={String(o.output_type)} content={o.content} />
          </GlassCard>
        ))}
        {outputs.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">
            No structured outputs yet. They are generated automatically when a call ends,
            or from Session Detail → Generate output.
          </GlassCard>
        )}
      </div>
    </div>
  );
}
