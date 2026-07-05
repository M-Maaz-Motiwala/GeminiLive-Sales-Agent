/** Same-origin by default — nginx proxies /api and /ws to platform. */
export const API_BASE = import.meta.env.VITE_API_URL ?? '';

let onUnauthorized: (() => void) | null = null;

/** Registered by AuthProvider — clears session and redirects via ProtectedRoute. */
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function parseError(body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  }
  return 'Request failed';
}

/**
 * Attempt a silent token refresh using the stored refresh token.
 * Returns a new access token on success, or null on failure.
 * Does NOT throw — callers use the boolean/null return to decide retry vs logout.
 */
export async function tryRefreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('aura_refresh_token');
  if (!refreshToken) return null;
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (data?.access_token) {
      localStorage.setItem('aura_token', data.access_token);
      if (data?.refresh_token) {
        localStorage.setItem('aura_refresh_token', data.refresh_token);
      }
      return data.access_token as string;
    }
    return null;
  } catch {
    return null;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body && !(init.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  // On 401, try one silent refresh + retry. If refresh fails, log out.
  if (res.status === 401) {
    const newToken = await tryRefreshAccessToken();
    if (newToken) {
      const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
      res = await fetch(`${API_BASE}${path}`, { ...init, headers: retryHeaders });
    }
    if (res.status === 401) {
      onUnauthorized?.();
      throw new Error('Session expired — please sign in again');
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(parseError(body));
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Like apiFetch but always returns an array (never throws on wrong shape after 401). */
export async function apiFetchList<T = unknown>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<T[]> {
  try {
    const data = await apiFetch<T[] | unknown>(path, token, init);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export async function apiFetchPublic<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  return apiFetch<T>(path, null, init);
}