import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { StickyNote, Trash2, Plus, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';
import { PageHeader, GlassCard, BtnGhost } from '@/src/components/admin/theme';
import { API_BASE, apiFetch, apiFetchList } from '@/src/lib/api';
import OrgFilter from '@/src/components/admin/OrgFilter';

const ENTITY_TYPES = ['', 'session', 'lead', 'contact'];

export default function Notes() {
  const { token } = useAuth();
  const [notes, setNotes] = useState<any[]>([]);
  const [entityType, setEntityType] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ entity_type: 'session', entity_id: '', content: '' });
  const [error, setError] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = () => {
    const params = new URLSearchParams();
    if (entityType) params.set('entity_type', entityType);
    if (organizationId) params.set('organization_id', organizationId);
    const qs = params.toString() ? `?${params}` : '';
    apiFetchList(`/api/notes${qs}`, token).then(setNotes);
  };

  useEffect(() => { load(); }, [token, entityType, organizationId]);

  const createNote = async () => {
    setError('');
    try {
      await apiFetch('/api/notes', token, {
        method: 'POST',
        body: JSON.stringify({
          entity_type: form.entity_type,
          entity_id: parseInt(form.entity_id, 10),
          content: form.content,
        }),
      });
      setForm({ entity_type: 'session', entity_id: '', content: '' });
      setShowForm(false);
      load();
    } catch (e: any) {
      setError(e.message || 'Failed to create note');
    }
  };

  const deleteNote = async (id: number) => {
    await fetch(`${API_BASE}/api/notes/${id}`, { method: 'DELETE', headers });
    load();
  };

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Notes"
        subtitle="Session summaries, agent notes, and CRM context"
        action={
          <BtnGhost onClick={() => setShowForm(v => !v)}>
            <Plus className="w-3.5 h-3.5" /> Add note
          </BtnGhost>
        }
      />

      {showForm && (
        <GlassCard className="p-4 mb-6 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <select
              value={form.entity_type}
              onChange={e => setForm(f => ({ ...f, entity_type: e.target.value }))}
              className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white"
            >
              <option value="session">session</option>
              <option value="lead">lead</option>
              <option value="contact">contact</option>
            </select>
            <input
              placeholder="Entity ID"
              value={form.entity_id}
              onChange={e => setForm(f => ({ ...f, entity_id: e.target.value }))}
              className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white"
            />
            <BtnGhost onClick={createNote}>Save</BtnGhost>
          </div>
          <textarea
            placeholder="Note content…"
            value={form.content}
            onChange={e => setForm(f => ({ ...f, content: e.target.value }))}
            rows={3}
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white resize-none"
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
        </GlassCard>
      )}

      <div className="flex flex-wrap gap-2 mb-6 items-center">
        <OrgFilter value={organizationId} onChange={setOrganizationId} className="mr-2" />
        {ENTITY_TYPES.map(t => (
          <button
            key={t || 'all'}
            onClick={() => setEntityType(t)}
            className={cn(
              'px-3 py-1.5 rounded-xl text-[10px] font-semibold uppercase tracking-wide transition-all',
              entityType === t
                ? 'bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white'
                : 'border border-white/10 text-zinc-400 hover:bg-white/5',
            )}
          >
            {t || 'all'}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {notes.map(n => (
          <GlassCard key={n.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-[10px] text-zinc-500 mb-2">
                  <StickyNote className="w-3 h-3" />
                  <span className="uppercase font-semibold text-violet-400">{n.entity_type}</span>
                  <span>#{n.entity_id}</span>
                  {n.entity_type === 'session' && (
                    <Link to={`/admin/sessions/${n.entity_id}`} className="text-cyan-400 hover:underline flex items-center gap-0.5">
                      View session <ExternalLink className="w-2.5 h-2.5" />
                    </Link>
                  )}
                  <span>· {new Date(n.created_at).toLocaleString()}</span>
                </div>
                <div className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap">{n.content}</div>
              </div>
              <button onClick={() => deleteNote(n.id)} className="text-zinc-600 hover:text-red-400 p-1">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </GlassCard>
        ))}
        {notes.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">
            No notes yet. Summaries are auto-saved here after each call, or add one manually.
          </GlassCard>
        )}
      </div>
    </div>
  );
}
