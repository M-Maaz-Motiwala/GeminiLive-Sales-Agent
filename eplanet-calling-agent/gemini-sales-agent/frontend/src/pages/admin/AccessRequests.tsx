import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { API_BASE } from '@/src/lib/api';

interface AccessRequest {
  id: number;
  user_id: number;
  email: string;
  full_name: string;
  designation: string;
  organization_id: number;
  organization_name: string;
  status: string;
  created_at: string;
}

interface ApprovedUser {
  id: number;
  email: string;
  full_name: string;
  designation: string;
  role: string;
  is_active: boolean;
  is_approved: boolean;
  auth_provider: string;
  google_picture?: string;
  organization_id: number | null;
  organization_name: string | null;
  created_at: string;
}

type Tab = 'requests' | 'approved';

export default function AccessRequests() {
  const { token, user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [tab, setTab] = useState<Tab>('requests');
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [approvedUsers, setApprovedUsers] = useState<ApprovedUser[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [actioningId, setActioningId] = useState<number | null>(null);

  const fetchRequests = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/access-requests?status=pending`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to load access requests');
      const data = await res.json();
      setRequests(data);
    } catch (err: any) {
      setError(err.message || 'Error loading requests');
    } finally {
      setLoading(false);
    }
  };

  const fetchApprovedUsers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to load approved users');
      const data = await res.json();
      setApprovedUsers(data);
    } catch (err: any) {
      setError(err.message || 'Error loading approved users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!token) return;
    if (tab === 'requests') fetchRequests();
    else fetchApprovedUsers();
  }, [token, tab]);

  const handleAction = async (id: number, action: 'approve' | 'reject') => {
    setActioningId(id);
    try {
      const res = await fetch(`${API_BASE}/api/access-requests/${id}/${action}`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || `Failed to ${action} request`);
      }
      setRequests((prev) => prev.filter((r) => r.id !== id));
      window.dispatchEvent(new CustomEvent('accessRequestsChanged'));
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActioningId(null);
    }
  };

  const handleRoleChange = async (id: number, newRole: 'user' | 'org_head' | 'admin') => {
    setActioningId(id);
    try {
      const res = await fetch(`${API_BASE}/api/users/${id}/role`, {
        method: 'PATCH',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ role: newRole }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to update role');
      }
      setApprovedUsers((prev) =>
        prev.map((u) => (u.id === id ? { ...u, role: newRole } : u)),
      );
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActioningId(null);
    }
  };

  const handleDeleteUser = async (u: ApprovedUser) => {
    const msg = u.role === 'admin'
      ? `Delete admin ${u.full_name || u.email}?\n\nAdmins must be demoted to a regular user before deletion. Demote them first, then delete.`
      : `Permanently delete ${u.full_name || u.email}?\n\nTheir leads, contacts, sessions, campaigns, and notes will be kept but unlinked. Their access requests and Google Calendar connection will be removed. This cannot be undone.`;
    if (!window.confirm(msg)) return;
    if (u.role === 'admin') return;
    setActioningId(u.id);
    try {
      const res = await fetch(`${API_BASE}/api/users/${u.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to delete user');
      }
      setApprovedUsers((prev) => prev.filter((x) => x.id !== u.id));
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActioningId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
      </div>
    );
  }

  const roleBadge = (role: string) => {
    const styles =
      role === 'admin'
        ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
        : role === 'org_head'
          ? 'bg-violet-500/10 text-violet-400 border-violet-500/20'
          : 'bg-slate-500/10 text-slate-400 border-slate-500/20';
    const label = role === 'admin' ? 'Admin' : role === 'org_head' ? 'Org Head' : 'User';
    return (
      <span
        className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-medium border ${styles}`}
      >
        {label}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">User Management</h1>
          <p className="text-sm text-slate-400">
            Review access requests and manage approved users.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-800">
        <button
          onClick={() => setTab('requests')}
          className={`px-4 py-2 text-sm font-medium transition ${
            tab === 'requests'
              ? 'border-b-2 border-indigo-500 text-white'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Access Requests
          {requests.length > 0 && (
            <span className="ml-2 inline-flex items-center rounded-full bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-400">
              {requests.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab('approved')}
          className={`px-4 py-2 text-sm font-medium transition ${
            tab === 'approved'
              ? 'border-b-2 border-indigo-500 text-white'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          Approved Users
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {tab === 'requests' ? (
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm text-slate-300">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/40 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  <th className="px-6 py-4">Requester</th>
                  <th className="px-6 py-4">Target Organization</th>
                  <th className="px-6 py-4">Designation</th>
                  <th className="px-6 py-4">Requested On</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {requests.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-slate-500">
                      No pending access requests.
                    </td>
                  </tr>
                ) : (
                  requests.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-800/25 transition">
                      <td className="px-6 py-4">
                        <div className="font-semibold text-white">{r.full_name}</div>
                        <div className="text-xs text-slate-500">{r.email}</div>
                      </td>
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-2 py-1 text-xs font-medium text-indigo-400 border border-indigo-500/20">
                          {r.organization_name}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-300 font-medium">{r.designation}</td>
                      <td className="px-6 py-4 text-slate-400">
                        {new Date(r.created_at).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          <button
                            onClick={() => handleAction(r.id, 'approve')}
                            disabled={actioningId !== null}
                            className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => handleAction(r.id, 'reject')}
                            disabled={actioningId !== null}
                            className="rounded-lg bg-rose-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-rose-500 disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm text-slate-300">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/40 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  <th className="px-6 py-4">User</th>
                  <th className="px-6 py-4">Organization</th>
                  <th className="px-6 py-4">Designation</th>
                  <th className="px-6 py-4">Role</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {approvedUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-slate-500">
                      No approved users yet.
                    </td>
                  </tr>
                ) : (
                  approvedUsers.map((u) => (
                    <tr key={u.id} className="hover:bg-slate-800/25 transition">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          {u.google_picture ? (
                            <img
                              src={u.google_picture}
                              alt=""
                              className="h-8 w-8 rounded-full object-cover"
                            />
                          ) : (
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-slate-300">
                              {(u.full_name || u.email || '?').charAt(0).toUpperCase()}
                            </div>
                          )}
                          <div>
                            <div className="font-semibold text-white">{u.full_name || '—'}</div>
                            <div className="text-xs text-slate-500">{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {u.organization_name ? (
                          <span className="inline-flex items-center rounded-md bg-indigo-500/10 px-2 py-1 text-xs font-medium text-indigo-400 border border-indigo-500/20">
                            {u.organization_name}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-500">—</span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-slate-300 font-medium">{u.designation || '—'}</td>
                      <td className="px-6 py-4">{roleBadge(u.role)}</td>
                      <td className="px-6 py-4 text-right">
                        {isAdmin ? (
                          <div className="flex justify-end gap-2">
                            {u.role !== 'org_head' && (
                              <button
                                onClick={() => handleRoleChange(u.id, 'org_head')}
                                disabled={actioningId !== null || !u.organization_id}
                                title={!u.organization_id ? 'Assign an organization first' : ''}
                                className="rounded-lg bg-violet-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-violet-500 disabled:opacity-50"
                              >
                                Make Org Head
                              </button>
                            )}
                            {u.role === 'org_head' && (
                              <button
                                onClick={() => handleRoleChange(u.id, 'user')}
                                disabled={actioningId !== null}
                                className="rounded-lg bg-slate-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-500 disabled:opacity-50"
                              >
                                Demote to User
                              </button>
                            )}
                            {u.role !== 'admin' && (
                              <button
                                onClick={() => handleRoleChange(u.id, 'admin')}
                                disabled={actioningId !== null}
                                className="rounded-lg bg-amber-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-amber-500 disabled:opacity-50"
                              >
                                Make Admin
                              </button>
                            )}
                            {u.role === 'admin' && u.id !== user?.id && (
                              <button
                                onClick={() => handleRoleChange(u.id, 'user')}
                                disabled={actioningId !== null}
                                className="rounded-lg bg-slate-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-500 disabled:opacity-50"
                              >
                                Demote to User
                              </button>
                            )}
                            {u.role !== 'admin' && (
                              <button
                                onClick={() => handleDeleteUser(u)}
                                disabled={actioningId !== null}
                                className="rounded-lg bg-red-600/80 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-red-500 disabled:opacity-50"
                              >
                                Delete
                              </button>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-500">Admin only</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}