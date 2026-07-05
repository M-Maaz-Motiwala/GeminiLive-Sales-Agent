import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetchList } from '@/src/lib/api';

const selectCls =
  'rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

type Org = { id: number; name: string; did?: string };

type Props = {
  value: string;
  onChange: (organizationId: string) => void;
  className?: string;
  showAll?: boolean;
};

export function useOrganizations() {
  const { token, user } = useAuth();
  const [organizations, setOrganizations] = useState<Org[]>([]);

  useEffect(() => {
    if (!token) return;
    apiFetchList<Org>('/api/organizations', token)
      .then(setOrganizations)
      .catch(() => setOrganizations([]));
  }, [token]);

  // Non-admins only ever see their own org (the backend enforces this too).
  const isAdmin = user?.role === 'admin';
  return isAdmin ? organizations : organizations.filter(o => o.id === user?.organization_id);
}

export default function OrgFilter({ value, onChange, className = '', showAll = true }: Props) {
  const { user } = useAuth();
  const organizations = useOrganizations();
  const isAdmin = user?.role === 'admin';

  // Non-admins: lock to their own org and render nothing.
  // The backend already scopes all list endpoints by the user's org, so the
  // filter dropdown is redundant for them.
  useEffect(() => {
    if (!isAdmin && user?.organization_id && !value) {
      onChange(String(user.organization_id));
    }
  }, [isAdmin, user?.organization_id, value, onChange]);

  if (!isAdmin) return null;

  return (
    <select
      className={`${selectCls} ${className}`}
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      {showAll && <option value="">All organizations</option>}
      {organizations.map(o => (
        <option key={o.id} value={o.id}>
          {o.name}{o.did ? ` — ${o.did}` : ''}
        </option>
      ))}
    </select>
  );
}

export function orgQueryParam(organizationId: string): string {
  return organizationId ? `organization_id=${organizationId}` : '';
}

export function appendOrgParam(path: string, organizationId: string): string {
  const q = orgQueryParam(organizationId);
  if (!q) return path;
  return path.includes('?') ? `${path}&${q}` : `${path}?${q}`;
}