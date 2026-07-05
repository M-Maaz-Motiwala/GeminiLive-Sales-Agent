import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetch, API_BASE } from '@/src/lib/api';
import { GlassCard, BtnPrimary, BtnGhost } from '@/src/components/admin/theme';
import { Calendar, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';

export default function CalendarSettings() {
  const { token } = useAuth();
  const [status, setStatus] = useState<{ connected: boolean; calendar_id: string | null }>({
    connected: false,
    calendar_id: null,
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [connecting, setConnecting] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/calendar/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to load Google Calendar status');
      const data = await res.json();
      setStatus(data);
    } catch (err: any) {
      setError(err.message || 'Error checking calendar status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (token) fetchStatus();
  }, [token]);

  const handleConnect = async () => {
    setConnecting(true);
    setError('');
    try {
      // Fetch the signed Google consent URL via an authenticated request
      // (bearer token travels in the Authorization header, not the URL).
      const data = await apiFetch<{ authorize_url: string }>(
        '/api/calendar/auth',
        token,
      );
      window.location.href = data.authorize_url;
    } catch (err: any) {
      setError(err.message || 'Failed to start Google Calendar connection');
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm('Are you sure you want to disconnect Google Calendar?')) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/calendar/disconnect`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to disconnect Google Calendar');
      setStatus({ connected: false, calendar_id: null });
    } catch (err: any) {
      setError(err.message || 'Error disconnecting calendar');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-indigo-400" />
      </div>
    );
  }

  return (
    <GlassCard className="p-6 space-y-4">
      <div className="flex items-start gap-4">
        <div className="p-3 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
          <Calendar className="w-6 h-6" />
        </div>
        <div className="space-y-1">
          <h2 className="text-sm font-semibold text-white">Google Calendar Integration</h2>
          <p className="text-xs text-zinc-500 max-w-md leading-relaxed">
            Connect your Google Calendar so the AI agent can read your availability and book discovery slots for you.
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-400">
          {error}
        </div>
      )}

      <div className="pt-2">
        {status.connected ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3.5 text-xs text-emerald-400">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <div>
                <p className="font-semibold text-emerald-300">Google Calendar Connected</p>
                <p className="text-emerald-500/80 mt-0.5">Primary Calendar ID: <span className="font-mono">{status.calendar_id}</span></p>
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleConnect}
                disabled={connecting}
                className="rounded-lg border border-white/10 bg-white/[0.02] hover:bg-white/[0.05] text-xs font-semibold text-white px-4 py-2 transition disabled:opacity-50"
              >
                {connecting ? 'Redirecting…' : 'Reconnect Calendar'}
              </button>
              <button
                onClick={handleDisconnect}
                className="rounded-lg bg-rose-600/10 border border-rose-500/20 hover:bg-rose-600/20 text-xs font-semibold text-rose-400 px-4 py-2 transition"
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/20 p-3.5 text-xs text-zinc-400">
              <AlertCircle className="w-4 h-4 text-zinc-500 shrink-0" />
              <span>No Google Calendar connected. Click below to authorise access.</span>
            </div>
            <BtnPrimary onClick={handleConnect} disabled={connecting}>
              {connecting ? 'Redirecting to Google…' : 'Connect Google Calendar'}
            </BtnPrimary>
          </div>
        )}
      </div>
    </GlassCard>
  );
}