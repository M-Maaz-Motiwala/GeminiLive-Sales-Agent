import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Contact } from 'lucide-react';
import { PageHeader, GlassCard, InputField } from '@/src/components/admin/theme';
import { apiFetchList } from '@/src/lib/api';

export default function Contacts() {
  const { token } = useAuth();
  const [contacts, setContacts] = useState<any[]>([]);
  const [search, setSearch] = useState('');

  const load = (q = '') => {
    const qs = q ? `?search=${encodeURIComponent(q)}` : '';
    apiFetchList(`/api/contacts${qs}`, token).then(setContacts);
  };

  useEffect(() => { load(); }, [token]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Contacts"
        subtitle="Directory — populated when the agent captures leads on calls"
        action={
          <div className="w-56">
            <InputField
              value={search}
              onChange={e => { setSearch(e.target.value); load(e.target.value); }}
              placeholder="Search contacts…"
            />
          </div>
        }
      />

      <div className="space-y-3">
        {contacts.map(c => (
          <Link key={c.id} to={`/admin/contacts/${c.id}`}>
            <GlassCard className="p-4 flex items-center gap-3 hover:border-cyan-500/30 transition-colors">
              <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-300">
                <Contact className="w-4 h-4" />
              </div>
              <div>
                <div className="text-sm font-medium text-white">{c.name}</div>
                <div className="text-xs text-zinc-500">
                  {[c.email, c.phone, c.company].filter(Boolean).join(' · ') || 'No details'}
                </div>
              </div>
            </GlassCard>
          </Link>
        ))}
        {contacts.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500 space-y-2">
            <p>No contacts yet.</p>
            <p className="text-xs text-zinc-600">
              Contacts appear when the agent uses create_lead during a call. See{' '}
              <Link to="/admin/leads" className="text-violet-400 hover:underline">Leads</Link> for CRM pipeline.
            </p>
          </GlassCard>
        )}
      </div>
    </div>
  );
}
