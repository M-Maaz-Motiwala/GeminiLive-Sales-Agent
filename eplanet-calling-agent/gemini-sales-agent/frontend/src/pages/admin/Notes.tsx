import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { StickyNote } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';
import { API_BASE, apiFetchList } from '@/src/lib/api';

const ENTITY_TYPES = ['lead', 'contact', 'session'];

export default function Notes() {
  const { token } = useAuth();
  const [notes, setNotes] = useState<any[]>([]);
  const [entityType, setEntityType] = useState('lead');
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    apiFetchList(`/api/notes?entity_type=${entityType}`, token).then(setNotes);
  }, [token, entityType]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader title="Notes" subtitle="Contextual notes from agent interactions" />

      <div className="flex flex-wrap gap-2 mb-6">
        {ENTITY_TYPES.map(t => (
          <button
            key={t}
            onClick={() => setEntityType(t)}
            className={cn(
              'px-3 py-1.5 rounded-xl text-[10px] font-semibold uppercase tracking-wide transition-all',
              entityType === t
                ? 'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white'
                : 'border border-white/10 text-zinc-400 hover:bg-white/5',
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {notes.map(n => (
          <GlassCard key={n.id} className="p-4">
            <div className="flex items-center gap-2 text-[10px] text-zinc-500 mb-2">
              <StickyNote className="w-3 h-3" />
              {n.entity_type} #{n.entity_id} · {new Date(n.created_at).toLocaleString()}
            </div>
            <div className="text-sm text-zinc-300">{n.content}</div>
          </GlassCard>
        ))}
        {notes.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">No notes found.</GlassCard>
        )}
      </div>
    </div>
  );
}
