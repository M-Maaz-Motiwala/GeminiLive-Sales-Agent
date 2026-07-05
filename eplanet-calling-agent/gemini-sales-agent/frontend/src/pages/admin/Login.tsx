import { useState, FormEvent, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { Headphones, Shield } from 'lucide-react';
import { BtnPrimary, InputField, GlassCard } from '@/src/components/admin/theme';

export default function Login() {
  const { login, googleLogin, isAuthenticated } = useAuth();
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
            <span className="text-xs font-semibold uppercase tracking-widest">Sign in to your account</span>
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
              placeholder="***********"
              required
              autoComplete="current-password"
            />
            <BtnPrimary type="submit" disabled={loading} className="w-full mt-2">
              {loading ? 'Signing in…' : 'Enter command center'}
            </BtnPrimary>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center" aria-hidden="true">
              <div className="w-full border-t border-white/[0.06]" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-[#0e0e17] px-2 text-zinc-500 font-semibold tracking-wider">Or</span>
            </div>
          </div>

          <button
            type="button"
            onClick={googleLogin}
            className="w-full flex items-center justify-center gap-3 px-4 py-2.5 rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.06] active:bg-white/[0.1] text-sm font-semibold text-white transition-all shadow-md hover:border-white/20"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" width="24" height="24" xmlns="http://www.w3.org/2000/svg">
              <g transform="matrix(1, 0, 0, 1, 0, 0)">
                <path d="M21.35,11.1H12v2.7h5.38c-0.24,1.28 -0.96,2.37 -2.04,3.1v2.6h3.3c1.93,-1.78 3.04,-4.4 3.04,-7.4C21.68,11.9 21.57,11.5 21.35,11.1z" fill="#4285F4" />
                <path d="M12,20.8c2.7,0 4.96,-0.9 6.6,-2.4l-3.3,-2.6c-0.9,0.6 -2.07,0.98 -3.3,0.98 -2.54,0 -4.69,-1.72 -5.46,-4.03H3.14v2.7C4.79,18.72 8.14,20.8 12,20.8z" fill="#34A853" />
                <path d="M6.54,12.75c-0.2,-0.6 -0.3,-1.2 -0.3,-1.8s0.1,-1.2 0.3,-1.8V6.45H3.14C2.4,7.93 2,9.6 2,11.4s0.4,3.47 1.14,4.95L6.54,12.75z" fill="#FBBC05" />
                <path d="M12,5.2c1.47,0 2.8,0.5 3.84,1.5l2.87,-2.87C16.96,2.22 14.7,1.3 12,1.3 8.14,1.3 4.79,3.38 3.14,6.45l3.4,2.7C7.31,6.85 9.46,5.2 12,5.2z" fill="#EA4335" />
              </g>
            </svg>
            Continue with Google
          </button>


          <p className="text-[11px] text-zinc-600 text-center mt-6 leading-relaxed">
            Default: <span className="text-zinc-500">admin@aura.ai</span> / <span className="text-zinc-500">**********</span>
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
