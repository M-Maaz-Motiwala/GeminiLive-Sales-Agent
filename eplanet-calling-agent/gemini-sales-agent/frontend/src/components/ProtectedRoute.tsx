import { Navigate } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { ReactNode } from 'react';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/admin/login" replace />;
  return <>{children}</>;
}
