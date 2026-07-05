import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, AlertCircle, CheckCircle2, Info, Server, Terminal, Sliders, Trash2 } from 'lucide-react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetch, apiFetchPublic, API_BASE } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary, BtnGhost } from '@/src/components/admin/theme';
import CalendarSettings from './CalendarSettings';

type DiagnosticCheck = {
  id: string;
  ok: boolean;
  message: string;
  owner: string;
  severity: string;
  hint?: string;
};

type DiagnosticsResponse = {
  generated_at: string;
  docker_available: boolean;
  containers: { name: string; status: string; state: string }[];
  checks: DiagnosticCheck[];
  summary: { ok: boolean; failed_count: number; failed_owners: string[] };
  telephony: Record<string, unknown>;
};

const LOG_SERVICES = [
  { id: 'gemini_bridge', label: 'Gemini bridge (calls, RTP stats)' },
  { id: 'asterisk', label: 'Asterisk (SIP, RTP)' },
  { id: 'aura_platform', label: 'Platform API' },
  { id: 'aura_celery', label: 'Celery worker' },
  { id: 'aura_frontend', label: 'Frontend' },
];

const OWNER_LABELS: Record<string, string> = {
  platform: 'Your codebase / deploy',
  devops: 'Server / firewall team',
  didww: 'DIDWW / telecom team',
};

function OwnerBadge({ owner }: { owner: string }) {
  const colors: Record<string, string> = {
    platform: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
    devops: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    didww: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border ${colors[owner] ?? 'bg-zinc-500/20 text-zinc-400'}`}>
      {OWNER_LABELS[owner] ?? owner}
    </span>
  );
}

function CheckRow({ check }: { check: DiagnosticCheck }) {
  const Icon = check.ok ? CheckCircle2 : check.severity === 'info' ? Info : AlertCircle;
  const iconClass = check.ok
    ? 'text-emerald-400'
    : check.severity === 'info'
      ? 'text-zinc-400'
      : 'text-amber-400';
  return (
    <div className="py-3 border-b border-white/[0.06] last:border-0">
      <div className="flex items-start gap-3">
        <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${iconClass}`} />
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm text-zinc-200">{check.message}</p>
            <OwnerBadge owner={check.owner} />
          </div>
          {check.hint && (
            <p className="text-xs text-zinc-500 leading-relaxed">{check.hint}</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Settings() {
  const { token, user, logout } = useAuth();
  const [sipInfo, setSipInfo] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResponse | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [logService, setLogService] = useState('gemini_bridge');
  const [logGrep, setLogGrep] = useState('rtp_in|Call ready|ERROR|Gemini');
  const [logs, setLogs] = useState('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsMeta, setLogsMeta] = useState('');

  // Concurrent call limit state
  const [concurrentLimit, setConcurrentLimit] = useState<number>(5);
  const [savingLimit, setSavingLimit] = useState<boolean>(false);
  const [limitSaved, setLimitSaved] = useState<boolean>(false);

  // Fetch concurrent call limit
  useEffect(() => {
    if (!token || user?.role !== 'admin') return;
    fetch(`${API_BASE}/api/system/concurrent-call-limit`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => {
        if (res.ok) return res.json();
        throw new Error();
      })
      .then(data => setConcurrentLimit(data.limit))
      .catch(e => console.error("Failed to load concurrent limit settings", e));
  }, [token, user]);

  const handleSaveLimit = async () => {
    setSavingLimit(true);
    setLimitSaved(false);
    try {
      const res = await fetch(`${API_BASE}/api/system/concurrent-call-limit`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ limit: concurrentLimit })
      });
      if (res.ok) {
        setLimitSaved(true);
        setTimeout(() => setLimitSaved(false), 3000);
      } else {
        const err = await res.json();
        alert(err.detail || "Failed to save concurrent limit");
      }
    } catch (e) {
      alert("Error saving concurrent limit");
    } finally {
      setSavingLimit(false);
    }
  };

  useEffect(() => {
    if (!token) return;
    apiFetchPublic<Record<string, string>>('/api/system/info')
      .then(d => { setSipInfo(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [token]);

  const runDiagnostics = useCallback(async () => {
    if (!token) return;
    setDiagLoading(true);
    try {
      const data = await apiFetch<DiagnosticsResponse>('/api/system/diagnostics', token);
      setDiagnostics(data);
    } catch (e) {
      setDiagnostics(null);
      console.error(e);
    } finally {
      setDiagLoading(false);
    }
  }, [token]);

  const fetchLogs = useCallback(async () => {
    if (!token) return;
    setLogsLoading(true);
    try {
      const params = new URLSearchParams({
        service: logService,
        tail: '200',
        since_minutes: '120',
      });
      if (logGrep.trim()) params.set('grep', logGrep.trim());
      const data = await apiFetch<{
        ok: boolean;
        logs?: string;
        lines?: number;
        error?: string;
      }>(`/api/system/logs?${params}`, token);
      if (data.ok && data.logs) {
        setLogs(data.logs);
        setLogsMeta(`${data.lines ?? 0} lines · ${logService}`);
      } else {
        setLogs(data.error ?? 'Failed to load logs');
        setLogsMeta('');
      }
    } catch (e) {
      setLogs(e instanceof Error ? e.message : 'Failed to load logs');
      setLogsMeta('');
    } finally {
      setLogsLoading(false);
    }
  }, [token, logService, logGrep]);

  useEffect(() => {
    if (token) runDiagnostics();
  }, [token, runDiagnostics]);

  // Account deletion (self)
  const [deletingSelf, setDeletingSelf] = useState(false);

  const handleDeleteSelf = async () => {
    if (!token) return;
    if (!window.confirm('This will permanently delete your account. Leads, contacts, sessions, and resources you own will be kept but unlinked from you. Continue?')) return;
    const typed = window.prompt(`Type your email (${user?.email}) to confirm permanent deletion:`);
    if (typed !== user?.email) {
      alert('Email did not match. Aborted.');
      return;
    }
    setDeletingSelf(true);
    try {
      await apiFetch('/api/users/me', token, { method: 'DELETE' });
      logout();
      window.location.href = '/';
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to delete account');
    } finally {
      setDeletingSelf(false);
    }
  };

  return (
    <div className="p-6 lg:p-10 space-y-6">
      <PageHeader
        title="Settings"
        subtitle={user?.role === 'admin' ? "Platform configuration, diagnostics, and Google Calendar" : "Google Calendar connection settings"}
        action={
          user?.role === 'admin' ? (
            <BtnGhost onClick={runDiagnostics} disabled={diagLoading}>
              <RefreshCw className={`w-4 h-4 ${diagLoading ? 'animate-spin' : ''}`} />
              Refresh diagnostics
            </BtnGhost>
          ) : undefined
        }
      />

      {/* Render Google Calendar Settings (For all authenticated & approved users) */}
      <CalendarSettings />

      {user?.role === 'admin' && (
        <>
          <GlassCard className="p-6 space-y-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Server className="w-4 h-4 text-violet-400" />
              Telephony diagnostics
            </h2>
            <p className="text-xs text-zinc-500">
              Run these checks from the admin UI when you cannot SSH to production. After an inbound test call,
              open <strong className="text-zinc-400">gemini_bridge</strong> logs and search for{' '}
              <code className="text-zinc-400">rtp_in</code> — if it stays <code className="text-zinc-400">0</code>,
              caller audio is not reaching the server (usually DIDWW whitelist or firewall).
            </p>

            {diagnostics && (
              <div className="text-xs text-zinc-600">
                Last run: {new Date(diagnostics.generated_at).toLocaleString()}
                {!diagnostics.docker_available && (
                  <span className="text-amber-400 ml-2">Docker socket not available — rebuild platform container</span>
                )}
              </div>
            )}

            {diagLoading && !diagnostics ? (
              <p className="text-sm text-zinc-500">Running checks…</p>
            ) : diagnostics ? (
              <>
                <div
                  className={`text-sm px-3 py-2 rounded-lg border ${
                    diagnostics.summary.ok
                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                      : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
                  }`}
                >
                  {diagnostics.summary.ok
                    ? 'All automated checks passed. If inbound still fails, use logs below during a test call.'
                    : `${diagnostics.summary.failed_count} issue(s) — owners: ${diagnostics.summary.failed_owners.map(o => OWNER_LABELS[o] ?? o).join(', ')}`}
                </div>
                <div className="divide-y divide-white/[0.04]">
                  {diagnostics.checks.map(c => (
                    <CheckRow key={c.id} check={c} />
                  ))}
                </div>
              </>
            ) : (
              <BtnPrimary onClick={runDiagnostics}>Run diagnostics</BtnPrimary>
            )}
          </GlassCard>

          {/* Concurrent Call Limit Config */}
          <GlassCard className="p-6 space-y-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Sliders className="w-4 h-4 text-emerald-400" />
              Platform Concurrent Call Limit
            </h2>
            <p className="text-xs text-zinc-500">
              Platform-wide concurrent calls limit inclusive of all organizations running outbound calls or campaigns. 
              Maximum capacity is capped at 50 (Asterisk UDP ports ceiling).
            </p>
            <div className="flex items-center gap-4 max-w-md pt-2">
              <input
                type="range"
                min="1"
                max="50"
                value={concurrentLimit}
                onChange={e => setConcurrentLimit(parseInt(e.target.value))}
                className="flex-1 accent-indigo-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer appearance-none"
              />
              <span className="text-sm font-semibold text-white bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg w-12 text-center">
                {concurrentLimit}
              </span>
              <BtnPrimary onClick={handleSaveLimit} disabled={savingLimit}>
                {savingLimit ? 'Saving…' : 'Save Limit'}
              </BtnPrimary>
            </div>
            {limitSaved && (
              <p className="text-xs text-emerald-400 font-medium">Platform concurrent call limit saved successfully.</p>
            )}
          </GlassCard>

          <GlassCard className="p-6 space-y-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Terminal className="w-4 h-4 text-cyan-400" />
              Container logs
            </h2>
            <p className="text-xs text-zinc-500">
              Admin-only. Secrets are redacted. Place an inbound call, then refresh bridge logs and look for{' '}
              <code className="text-zinc-400">STATS … rtp_in=</code> and <code className="text-zinc-400">Call ready</code>.
            </p>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="text-xs text-zinc-500 space-y-1">
                Container
                <select
                  value={logService}
                  onChange={e => setLogService(e.target.value)}
                  className="block mt-1 bg-zinc-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200"
                >
                  {LOG_SERVICES.map(s => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-zinc-500 space-y-1 flex-1 min-w-[200px]">
                Filter (substring)
                <input
                  value={logGrep}
                  onChange={e => setLogGrep(e.target.value)}
                  placeholder="rtp_in, ERROR, StasisStart…"
                  className="block w-full mt-1 bg-zinc-900 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200"
                />
              </label>
              <BtnPrimary onClick={fetchLogs} disabled={logsLoading}>
                {logsLoading ? 'Loading…' : 'Load logs'}
              </BtnPrimary>
            </div>
            {logsMeta && <p className="text-[11px] text-zinc-600">{logsMeta}</p>}
            <pre className="text-[11px] leading-relaxed text-zinc-400 bg-black/40 border border-white/[0.06] rounded-xl p-4 max-h-[420px] overflow-auto whitespace-pre-wrap font-mono">
              {logs || 'Click “Load logs” (run a test call first for best results).'}
            </pre>
          </GlassCard>

          <GlassCard className="p-6 space-y-3">
            <h2 className="text-sm font-semibold text-white">Who fixes what?</h2>
            <dl className="text-xs text-zinc-400 space-y-3">
              <div>
                <dt className="text-violet-300 font-medium">Your codebase / deploy</dt>
                <dd className="mt-1">EXTERNAL_IP in .env, ./start.sh, bridge/Gemini errors, agent config, CRM org DIDs</dd>
              </div>
              <div>
                <dt className="text-amber-300 font-medium">Server / firewall team</dt>
                <dd className="mt-1">UDP 5060, UDP 10000–10050 open on host + cloud security group (not only 16384–32767)</dd>
              </div>
              <div>
                <dt className="text-cyan-300 font-medium">DIDWW / telecom team</dt>
                <dd className="mt-1">Voice-IN routing to your public IP, inbound trunk Allowed RTP IPs, DID routing</dd>
              </div>
            </dl>
          </GlassCard>

          <GlassCard className="p-6 space-y-3">
            <h2 className="text-sm font-semibold text-white">Organizations & DIDs</h2>
            <p className="text-xs text-zinc-500">
              New DIDs are written to <code className="text-zinc-400">asterisk/generated/org-dids.conf</code> when you
              create an organization. Point the number at your Asterisk trunk in DIDWW.
            </p>
            {loading ? (
              <p className="text-sm text-zinc-500">Loading…</p>
            ) : (
              <dl className="text-sm text-zinc-400 space-y-2">
                {sipInfo.sip_server && (
                  <div className="flex gap-2"><dt className="text-zinc-500 w-28">SIP server</dt><dd>{sipInfo.sip_server}</dd></div>
                )}
                {sipInfo.sip_port && (
                  <div className="flex gap-2"><dt className="text-zinc-500 w-28">SIP port</dt><dd>{sipInfo.sip_port}</dd></div>
                )}
              </dl>
            )}
          </GlassCard>
        </>
      )}

      {/* Account deletion — available to all authenticated users */}
      <GlassCard className="p-6 space-y-3 border-red-500/20">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <Trash2 className="w-4 h-4 text-red-400" />
          Delete account
        </h2>
        <p className="text-xs text-zinc-500 leading-relaxed">
          Permanently delete your account. Your leads, contacts, sessions, campaigns, agents, and notes are
          <strong className="text-zinc-400"> kept</strong> but unlinked from you. Your access requests and Google
          Calendar connection are removed. This action cannot be undone.
        </p>
        <div className="pt-1">
          <button
            onClick={handleDeleteSelf}
            disabled={deletingSelf}
            className="inline-flex items-center gap-2 text-sm font-medium text-red-300 bg-red-500/10 border border-red-500/30 hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg px-4 py-2 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            {deletingSelf ? 'Deleting…' : 'Delete my account'}
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
