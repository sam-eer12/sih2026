// apiClient.ts — talking to our own route handlers from the browser.
//
// The ID token is read fresh from the Firebase SDK on every call and sent as a
// bearer header. It is never cached here and never read from the cookie: the
// cookie is a presence marker for the route gate, and the token is the thing
// requireUser() actually verifies.
'use client';

import { getIdToken } from './firebase/client';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** Persistence is switched off server-side rather than broken. */
  get isUnconfigured(): boolean {
    return this.status === 503;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getIdToken();
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    // The body is our own error shape, but never assume — a proxy or a crash
    // can return HTML, and JSON.parse failing would hide the real status.
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body?.error) message = body.error;
    } catch {
      /* keep the status-based message */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export const apiGet = <T,>(path: string) => request<T>(path);
export const apiPost = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });
export const apiPatch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
