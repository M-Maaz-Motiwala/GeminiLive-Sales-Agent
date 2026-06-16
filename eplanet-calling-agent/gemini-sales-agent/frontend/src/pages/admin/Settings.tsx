import { useEffect, useState } from 'react';
import { useAuth } from '@/src/auth/AuthContext';
import { apiFetch } from '@/src/lib/api';
import { PageHeader, GlassCard, BtnPrimary } from '@/src/components/admin/theme';
import { cn } from '@/lib/utils';

const inputCls =
  'w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50';

export default function Settings() {
  const { token } = useAuth();
  const [masterPrompt, setMasterPrompt] = useState('');
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    apiFetch<{ master_prompt: string | null }>('/api/system/settings', token)
      .then(d => { setMasterPrompt(d.master_prompt ?? ''); setLoading(false); })
      .catch(() => setLoading(false));
  }, [token]);

  const save = async () => {
    setSaved(false);
    setError('');
    try {
      await apiFetch('/api/system/settings', token, {
        method: 'PUT',
        body: JSON.stringify({ master_prompt: masterPrompt.trim() || null }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    }
  };

  return (
    <div className="p-6 lg:p-10 space-y-6">
      <PageHeader
        title="Platform Settings"
        subtitle="Global configuration — applies to all agents unless overridden per-agent"
      />

      <GlassCard className="p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-white mb-1">Global Master Prompt</h2>
          <p className="text-xs text-zinc-500 mb-3">
            Injected at the top of every agent's system instruction before their inbound/outbound persona prompt.
            Controls universal call behavior: voice rules, lead capture quality, tool usage, call ending.
            Leave blank to use the built-in default. Each agent can further override this with their own master prompt override.
          </p>
          {loading ? (
            <p className="text-sm text-zinc-500">Loading…</p>
          ) : (
            <textarea
              rows={20}
              className={cn(inputCls, 'resize-y font-mono text-xs')}
              placeholder="Leave blank to use the built-in default master prompt…"
              value={masterPrompt}
              onChange={e => setMasterPrompt(e.target.value)}
            />
          )}
        </div>

        {error && (
          <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2">
            {error}
          </p>
        )}
        {saved && (
          <p className="text-sm text-green-400 bg-green-500/10 border border-green-500/30 rounded-xl px-4 py-2">
            Settings saved.
          </p>
        )}

        <BtnPrimary onClick={save} className="w-full sm:w-auto">Save Settings</BtnPrimary>
      </GlassCard>
    </div>
  );
}
