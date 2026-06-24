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

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (res.status === 401) {
    onUnauthorized?.();
    throw new Error('Session expired — please sign in again');
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
