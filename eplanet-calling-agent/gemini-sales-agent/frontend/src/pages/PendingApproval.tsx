import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { API_BASE } from '@/src/lib/api';

export default function PendingApproval() {
  const { user, token, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [checking, setChecking] = useState<boolean>(false);
  const [orgName, setOrgName] = useState<string>('');

  // Auto-redirect if user becomes approved
  useEffect(() => {
    if (user?.is_approved) {
      navigate('/admin', { replace: true });
    }
  }, [user, navigate]);

  // Fetch the selected organization's name
  useEffect(() => {
    if (!token || !user?.organization_id) return;
    fetch(`${API_BASE}/api/organizations/${user.organization_id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error();
      })
      .then((data) => setOrgName(data.name))
      .catch(() => setOrgName(`ID: ${user.organization_id}`));
  }, [token, user]);

  // Poll user status every 5 seconds
  useEffect(() => {
    if (!token || user?.is_approved) return;
    const interval = setInterval(() => {
      refreshUser();
    }, 5000);
    return () => clearInterval(interval);
  }, [token, user, refreshUser]);

  const handleCheckNow = async () => {
    setChecking(true);
    await refreshUser();
    setChecking(false);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#090b11] px-4 py-12 text-slate-100 font-sans">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.06),transparent_45%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_bottom_left,rgba(168,85,247,0.05),transparent_40%)]" />

      <div className="relative w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/60 p-8 backdrop-blur-xl shadow-2xl text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-8 h-8 animate-pulse">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
          </svg>
        </div>

        <h2 className="text-2xl font-bold tracking-tight text-white mb-2">Approval Pending</h2>
        <p className="text-sm text-slate-400 mb-6">
          Your access request has been submitted and is currently being reviewed.
        </p>

        <div className="mb-8 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-left space-y-3">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500 font-semibold uppercase tracking-wider">Account</span>
            <span className="text-slate-300 font-medium">{user?.email}</span>
          </div>
          <div className="flex justify-between text-xs border-t border-slate-800 pt-3">
            <span className="text-slate-500 font-semibold uppercase tracking-wider">Organization</span>
            <span className="text-slate-300 font-medium">{orgName || 'Loading...'}</span>
          </div>
          <div className="flex justify-between text-xs border-t border-slate-800 pt-3">
            <span className="text-slate-500 font-semibold uppercase tracking-wider">Designation</span>
            <span className="text-slate-300 font-medium">{user?.designation}</span>
          </div>
        </div>

        <div className="space-y-3">
          <button
            onClick={handleCheckNow}
            disabled={checking}
            className="w-full rounded-lg bg-indigo-600/10 hover:bg-indigo-600/20 active:bg-indigo-600/30 border border-indigo-500/20 py-2.5 font-semibold text-indigo-400 transition disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {checking ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-400 border-t-transparent" />
                Checking status...
              </>
            ) : (
              'Check Status Now'
            )}
          </button>

          <button
            onClick={() => {
              logout();
              navigate('/admin/login');
            }}
            className="w-full text-sm font-medium text-slate-500 hover:text-white transition py-2"
          >
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
