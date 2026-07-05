import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';

export default function GoogleCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { setSession, user } = useAuth();

  useEffect(() => {
    const accessToken = searchParams.get('access_token');
    const refreshToken = searchParams.get('refresh_token');

    if (accessToken) {
      // setSession writes tokens into React state + localStorage and fetches /me,
      // so ProtectedRoute sees the session immediately (no reload needed).
      setSession(accessToken, refreshToken || undefined).then(() => {
        // Route based on approval status — mirrors ProtectedRoute logic.
        navigate('/admin', { replace: true });
      });
    } else {
      navigate('/admin/login', { replace: true });
    }
  }, [searchParams, navigate, setSession]);

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center bg-slate-950 text-white">
      <div className="flex flex-col items-center gap-4">
        <div className="h-12 w-12 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent"></div>
        <p className="text-lg font-medium text-slate-300 animate-pulse">Completing Google authentication...</p>
      </div>
    </div>
  );
}