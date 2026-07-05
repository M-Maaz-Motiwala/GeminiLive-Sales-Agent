import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/src/auth/AuthContext';
import { ReactNode } from 'react';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) return <Navigate to="/admin/login" replace />;

  if (user && !user.is_approved) {
    const hasSubmitted = user.organization_id && user.designation;
    if (!hasSubmitted) {
      if (location.pathname !== '/access-request-form') {
        return <Navigate to="/access-request-form" replace />;
      }
    } else {
      if (location.pathname !== '/pending-approval') {
        return <Navigate to="/pending-approval" replace />;
      }
    }
  }

  return <>{children}</>;
}
