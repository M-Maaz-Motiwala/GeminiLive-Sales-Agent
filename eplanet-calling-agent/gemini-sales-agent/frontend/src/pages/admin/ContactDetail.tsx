import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { ArrowLeft, Contact, Loader2 } from 'lucide-react';
import { PageHeader, GlassCard } from '@/src/components/admin/theme';
import { apiFetch } from '@/src/lib/api';

export default function ContactDetail() {
  const { id } = useParams();
  const { token } = useAuth();
  const [contact, setContact] = useState<any | null>(null);

  useEffect(() => {
    if (!token || !id) return;
    apiFetch(`/api/contacts/${id}`, token)
      .then(setContact)
      .catch(() => setContact(null));
  }, [token, id]);

  if (!contact) {
    return (
      <div className="p-8 flex items-center gap-2 text-zinc-500">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading contact…
      </div>
    );
  }

  const rows = [
    ['Email', contact.email],
    ['Phone', contact.phone],
    ['Company', contact.company],
    ['Notes', contact.notes],
  ].filter(([, v]) => v);

  return (
    <div className="p-6 lg:p-8 max-w-2xl">
      <Link
        to="/admin/contacts"
        className="inline-flex items-center gap-1.5 text-xs text-zinc-500 hover:text-violet-400 mb-6"
      >
        <ArrowLeft className="w-3.5 h-3.5" /> Back to contacts
      </Link>

      <PageHeader
        title={contact.name || 'Contact'}
        subtitle={contact.company || 'Contact directory'}
        action={
          <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-300">
            <Contact className="w-5 h-5" />
          </div>
        }
      />

      <GlassCard className="p-6 space-y-4">
        {rows.length === 0 ? (
          <p className="text-sm text-zinc-500">No contact details on file yet.</p>
        ) : (
          <dl className="space-y-3">
            {rows.map(([label, value]) => (
              <div key={label} className="flex flex-col sm:flex-row sm:gap-4 text-sm">
                <dt className="text-zinc-500 shrink-0 w-24">{label}</dt>
                <dd className="text-white break-all">{value}</dd>
              </div>
            ))}
          </dl>
        )}
        {(contact.tags || []).length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-2 border-t border-white/5">
            {contact.tags.map((t: string) => (
              <span key={t} className="text-[10px] px-2 py-0.5 rounded bg-white/5 text-zinc-400">
                {t}
              </span>
            ))}
          </div>
        )}
        <p className="text-[10px] text-zinc-600 pt-2">
          Added {contact.created_at ? new Date(contact.created_at).toLocaleString() : '—'}
        </p>
      </GlassCard>
    </div>
  );
}
