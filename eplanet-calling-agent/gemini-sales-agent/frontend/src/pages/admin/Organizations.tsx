import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { Plus, Pencil, Trash2, X, Building2 } from 'lucide-react';
import { API_BASE, apiFetch, apiFetchList } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost, Badge } from '@/src/components/admin/theme';

const inputCls = 'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

const EMPTY = { name: '', did: '', is_active: true };

export default function Organizations() {
  const { token } = useAuth();
  const [orgs, setOrgs] = useState<any[]>([]);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const load = () => {
    if (!token) return;
    apiFetchList('/api/organizations', token).then(setOrgs).catch(() => setOrgs([]));
  };

  useEffect(() => { load(); }, [token]);

  const save = async () => {
    setError('');
    if (!form.name.trim() || !form.did.trim()) {
      setError('Name and DID are required');
      return;
    }
    const res = await fetch(
      editing ? `${API_BASE}/api/organizations/${editing.id}` : `${API_BASE}/api/organizations`,
      { method: editing ? 'PUT' : 'POST', headers, body: JSON.stringify(form) },
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setError(typeof err.detail === 'string' ? err.detail : err.detail?.[0]?.msg || 'Save failed');
      return;
    }
    setOpen(false);
    load();
  };

  const del = async (id: number) => {
    if (!confirm('Delete this organization?')) return;
    const res = await fetch(`${API_BASE}/api/organizations/${id}`, { method: 'DELETE', headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(typeof err.detail === 'string' ? err.detail : 'Delete failed');
      return;
    }
    load();
  };

  return (
    <div className="p-6 lg:p-10">
      <PageHeader
        title="Organizations"
        subtitle="Register a DID here — Asterisk dialplan updates automatically; then create agents under this org"
        action={
          <BtnPrimary onClick={() => { setEditing(null); setForm({ ...EMPTY }); setError(''); setOpen(true); }}>
            <Plus className="w-4 h-4" /> New organization
          </BtnPrimary>
        }
      />

      <div className="grid gap-3">
        {orgs.map(o => (
          <GlassCard key={o.id} className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <Building2 className="w-4 h-4 text-violet-400" />
                <span className="font-semibold text-white">{o.name}</span>
                {o.is_active && <Badge variant="success">Active</Badge>}
                <Badge variant="default">DID {o.did}</Badge>
              </div>
              <p className="text-xs text-zinc-500 mt-1">{o.agent_count || 0} active agent{(o.agent_count || 0) !== 1 ? 's' : ''}</p>
              <p className="text-xs text-violet-400/80 mt-2">
                Inbound to {o.did} routes to this org&apos;s agent pool · Outbound uses this caller ID
              </p>
            </div>
            <div className="flex gap-2">
              <BtnGhost onClick={() => { setEditing(o); setForm({ name: o.name, did: o.did, is_active: o.is_active }); setOpen(true); }}>
                <Pencil className="w-4 h-4" /> Edit
              </BtnGhost>
              <BtnGhost className="text-red-400 border-red-500/20 hover:bg-red-500/10" onClick={() => del(o.id)}>
                <Trash2 className="w-4 h-4" />
              </BtnGhost>
            </div>
          </GlassCard>
        ))}
        {orgs.length === 0 && <p className="text-zinc-600 text-sm">No organizations yet. Create one to register a DID.</p>}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-black/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="w-full max-w-lg bg-[#0c0c12] border-l border-white/10 h-full overflow-auto p-6 space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-white">{editing ? 'Edit organization' : 'New organization'}</h3>
              <button onClick={() => setOpen(false)} className="text-zinc-500 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            {error && <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2">{error}</p>}
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Organization name</label>
              <input className={inputCls} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Wherego" />
            </div>
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">DID (phone number)</label>
              <input className={inputCls} value={form.did} onChange={e => setForm(f => ({ ...f, did: e.target.value }))} placeholder="+13105550100" />
              <p className="text-xs text-zinc-500 mt-1">Must be routed to your Asterisk trunk at DIDWW. CRM registers it in generated dialplan automatically.</p>
            </div>
            <label className="flex items-center gap-2 text-sm text-zinc-400">
              <input type="checkbox" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} className="accent-violet-600" />
              Active
            </label>
            <BtnPrimary onClick={save} className="w-full">{editing ? 'Save' : 'Create & register DID'}</BtnPrimary>
          </div>
        </div>
      )}
    </div>
  );
}
