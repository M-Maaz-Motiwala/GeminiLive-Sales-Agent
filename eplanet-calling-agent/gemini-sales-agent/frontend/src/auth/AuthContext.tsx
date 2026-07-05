import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';

interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  is_approved: boolean;
  auth_provider: string;
  google_picture?: string;
  organization_id?: number;
  designation?: string;
}

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  googleLogin: () => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
  setSession: (accessToken: string, refreshToken?: string) => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

import { API_BASE, setUnauthorizedHandler } from '@/src/lib/api';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('aura_token'));
  const [user, setUser] = useState<AuthUser | null>(() => {
    const u = localStorage.getItem('aura_user');
    return u ? JSON.parse(u) : null;
  });

  const logout = useCallback(() => {
    localStorage.removeItem('aura_token');
    localStorage.removeItem('aura_refresh_token');
    localStorage.removeItem('aura_user');
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  // Reject expired/invalid tokens stored in localStorage (avoids 401 + .map crashes).
  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async res => {
        if (!res.ok) {
          logout();
          return;
        }
        const me = await res.json();
        setUser(me);
        localStorage.setItem('aura_user', JSON.stringify(me));
      })
      .catch(() => logout());
  }, [token, logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error('Invalid credentials');
    const data = await res.json();

    const meRes = await fetch(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });
    const me = await meRes.json();

    localStorage.setItem('aura_token', data.access_token);
    localStorage.setItem('aura_user', JSON.stringify(me));
    if (data.refresh_token) {
      localStorage.setItem('aura_refresh_token', data.refresh_token);
    }
    setToken(data.access_token);
    setUser(me);
  }, []);

  const googleLogin = useCallback(() => {
    window.location.href = `${API_BASE}/api/auth/google`;
  }, []);

  const refreshUser = useCallback(async () => {
    // Always read the latest token from localStorage — setSession may have just
    // written it without the closure seeing the new state value yet.
    const currentToken = localStorage.getItem('aura_token');
    if (!currentToken) return;
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${currentToken}` }
      });
      if (res.ok) {
        const me = await res.json();
        setUser(me);
        localStorage.setItem('aura_user', JSON.stringify(me));
        setToken(currentToken);
      }
    } catch (e) {
      console.error("Failed to refresh user:", e);
    }
  }, []);

  /**
   * Set tokens directly into React state + localStorage, then fetch /me.
   * Used by the Google OAuth callback page so ProtectedRoute sees the session
   * immediately without requiring a page reload.
   */
  const setSession = useCallback(async (accessToken: string, refreshToken?: string) => {
    localStorage.setItem('aura_token', accessToken);
    if (refreshToken) {
      localStorage.setItem('aura_refresh_token', refreshToken);
    }
    setToken(accessToken);
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (res.ok) {
        const me = await res.json();
        setUser(me);
        localStorage.setItem('aura_user', JSON.stringify(me));
      }
    } catch (e) {
      console.error("Failed to fetch user after setSession:", e);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, googleLogin, logout, refreshUser, setSession, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}