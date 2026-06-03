import { useState, FormEvent, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Headphones, Shield } from 'lucide-react';
import { BtnPrimary, InputField, GlassCard } from '@/src/components/admin/theme';

export default function Login() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('admin@aura.ai');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated) navigate('/admin', { replace: true });
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/admin');
    } catch {
      setError('Invalid email or password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#07070b] flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[800px] h-[500px] bg-gradient-to-b from-violet-600/20 via-fuchsia-600/10 to-transparent rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-0 right-0 h-1/2 bg-gradient-to-t from-cyan-950/30 to-transparent" />
      </div>

      <div className="relative w-full max-w-md">
        <div className="text-center mb-10">
          <div className="inline-flex p-4 rounded-2xl bg-gradient-to-br from-violet-600 to-fuchsia-600 shadow-2xl shadow-violet-900/50 mb-6">
            <Headphones className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-white mb-2">Aura Call Center</h1>
          <p className="text-sm text-zinc-500">AI voice agents · SIP · Knowledge base · CRM</p>
        </div>

        <GlassCard className="p-8">
          <div className="flex items-center gap-2 mb-6 text-zinc-400">
            <Shield className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-widest">Admin sign in</span>
          </div>

          {error && (
            <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <InputField
              label="Email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
            <InputField
              label="Password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="changeme123"
              required
              autoComplete="current-password"
            />
            <BtnPrimary type="submit" disabled={loading} className="w-full mt-2">
              {loading ? 'Signing in…' : 'Enter command center'}
            </BtnPrimary>
          </form>

          <p className="text-[11px] text-zinc-600 text-center mt-6 leading-relaxed">
            Default: <span className="text-zinc-500">admin@aura.ai</span> / <span className="text-zinc-500">changeme123</span>
            <br />
            Change in <code className="text-violet-400/80">.env</code> → ADMIN_EMAIL / ADMIN_PASSWORD
          </p>
        </GlassCard>

        <p className="text-center text-[11px] text-zinc-700 mt-8">
          Calls from Zoiper · Dial 701 / 702 / 703 · Not browser mic
        </p>
      </div>
    </div>
  );
}
