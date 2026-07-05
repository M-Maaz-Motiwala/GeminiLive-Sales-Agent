import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { API_BASE } from '@/src/lib/api';

interface Organization {
  id: number;
  name: string;
}

export default function AccessRequestForm() {
  const { user, token, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<string>('');
  const [designation, setDesignation] = useState<string>('');
  const [fullName, setFullName] = useState<string>(user?.full_name || '');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/api/organizations/available`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load organizations');
        return res.json();
      })
      .then((data) => setOrgs(data))
      .catch((err) => console.error(err));
  }, [token]);

  // If already approved, skip this form
  useEffect(() => {
    if (user?.is_approved) {
      navigate('/admin', { replace: true });
    }
  }, [user, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrg) {
      setError('Please select an organization');
      return;
    }
    if (!designation.trim()) {
      setError('Please enter your designation');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_BASE}/api/access-requests`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          organization_id: parseInt(selectedOrg),
          full_name: fullName,
          designation: designation,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to submit request');
      }

      await refreshUser();
      navigate('/pending-approval', { replace: true });
    } catch (err: any) {
      setError(err.message || 'Submission failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#090b11] px-4 py-12 text-slate-100 font-sans">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.08),transparent_45%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_bottom_left,rgba(168,85,247,0.06),transparent_40%)]" />

      <div className="relative w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/60 p-8 backdrop-blur-xl shadow-2xl">
        <div className="flex flex-col items-center mb-8">
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/25">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-white">Access Request</h2>
          <p className="mt-2 text-center text-sm text-slate-400">
            Tell us about your organization and role to activate your account.
          </p>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              Full Name
            </label>
            <input
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950/50 px-4 py-2.5 text-slate-100 placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:bg-slate-950"
              placeholder="e.g. John Doe"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              Select Organization
            </label>
            <select
              required
              value={selectedOrg}
              onChange={(e) => setSelectedOrg(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950/50 px-4 py-2.5 text-slate-100 outline-none transition focus:border-indigo-500 focus:bg-slate-950 appearance-none cursor-pointer"
            >
              <option value="" className="bg-slate-900 text-slate-400">-- Choose your organization --</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id.toString()} className="bg-slate-900 text-slate-100">
                  {o.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              Your Designation
            </label>
            <input
              type="text"
              required
              value={designation}
              onChange={(e) => setDesignation(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950/50 px-4 py-2.5 text-slate-100 placeholder-slate-500 outline-none transition focus:border-indigo-500 focus:bg-slate-950"
              placeholder="e.g. Outbound Rep, Sales Manager"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-indigo-600 py-3 font-semibold text-white transition hover:bg-indigo-500 active:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-indigo-600/25"
          >
            {loading ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Submitting...
              </>
            ) : (
              'Submit Access Request'
            )}
          </button>
        </form>

        <div className="mt-8 flex justify-center border-t border-slate-800 pt-6">
          <button
            onClick={() => {
              logout();
              navigate('/admin/login');
            }}
            className="text-sm font-medium text-slate-400 transition hover:text-white"
          >
            Sign Out
          </button>
        </div>
      </div>
    </div>
  );
}
