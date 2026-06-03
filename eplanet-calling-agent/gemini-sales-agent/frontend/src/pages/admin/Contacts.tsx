import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Contact } from 'lucide-react';
import { PageHeader, GlassCard, InputField } from '@/src/components/admin/theme';
import { API_BASE } from '@/src/lib/api';

export default function Contacts() {
  const { token } = useAuth();
  const [contacts, setContacts] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const headers = { Authorization: `Bearer ${token}` };

  const load = (q = '') => {
    const qs = q ? `?search=${encodeURIComponent(q)}` : '';
    fetch(`${API_BASE}/api/contacts${qs}`, { headers }).then(r => r.json()).then(setContacts).catch(() => {});
  };

  useEffect(() => { load(); }, [token]);

  return (
    <div className="p-6 lg:p-8">
      <PageHeader
        title="Contacts"
        subtitle="Contact directory"
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
          <GlassCard key={c.id} className="p-4 flex items-center gap-3">
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-300">
              <Contact className="w-4 h-4" />
            </div>
            <div>
              <div className="text-sm font-medium text-white">{c.name}</div>
              <div className="text-xs text-zinc-500">{c.email} · {c.phone} · {c.company}</div>
            </div>
          </GlassCard>
        ))}
        {contacts.length === 0 && (
          <GlassCard className="p-12 text-center text-sm text-zinc-500">No contacts found.</GlassCard>
        )}
      </div>
    </div>
  );
}
