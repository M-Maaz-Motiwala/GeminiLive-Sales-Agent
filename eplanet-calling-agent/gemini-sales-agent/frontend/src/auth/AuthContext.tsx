import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';

interface AuthUser { id: number; email: string; full_name: string; role: string; }

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
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
    setToken(data.access_token);
    setUser(me);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
