/**
 * Member account calls (API.md 5.17). The browser talks only to this API: it keeps the tokens in
 * HttpOnly cookies, so this module never sees one. Calls send credentials explicitly; the public
 * reads in `client.ts` stay credential-free CORS simple requests (PF 16.1).
 *
 * Writes that need a session send the synchronizer token from `GET /auth/csrf`. A rejected token
 * is fetched again and the write retried once (the session may have rotated).
 */

import type { AuthSession } from '../types';
import { ApiError, apiRequest } from './client';

const BASE = '/api/v1/auth';

let csrfToken: string | null = null;

export function forgetCsrfToken(): void {
  csrfToken = null;
}

async function csrf(): Promise<string> {
  if (csrfToken === null) {
    const { csrf_token } = await apiRequest<{ csrf_token: string }>(`${BASE}/csrf`, { credentials: 'include' });
    csrfToken = csrf_token;
  }
  return csrfToken;
}

interface CallOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  /** True for a write made with a session cookie: it carries `X-CSRF-Token`. */
  session?: boolean;
}

export async function call<T>(path: string, { method = 'POST', body, session = false }: CallOptions = {}): Promise<T> {
  const attempt = async (): Promise<T> =>
    apiRequest<T>(path.startsWith('/api/') ? path : `${BASE}${path}`, {
      method,
      body,
      credentials: 'include',
      headers: session ? { 'X-CSRF-Token': await csrf() } : undefined,
    });
  try {
    return await attempt();
  } catch (error) {
    if (session && error instanceof ApiError && error.code === 'CSRF_INVALID') {
      forgetCsrfToken();
      return attempt();
    }
    throw error;
  }
}

/** Never a 401: an anonymous visitor gets `{ authenticated: false }`. */
export const getSession = (): Promise<AuthSession> => call<AuthSession>('/session', { method: 'GET' });

export const register = (input: { email: string; password: string; display_name: string; turnstile_token?: string | null }) =>
  call<{ status: string }>('/register', { body: { ...input, turnstile_token: input.turnstile_token ?? undefined } });

export const verifyEmail = (tokenHash: string) => call<{ status: string }>('/verify-email', { body: { token_hash: tokenHash } });

export const resendVerification = (email: string) => call<{ status: string }>('/resend-verification', { body: { email } });

export async function login(email: string, password: string): Promise<AuthSession> {
  const session = await call<AuthSession>('/login', { body: { email, password } });
  forgetCsrfToken(); // a new session has a new token
  return session;
}

export async function logout(): Promise<void> {
  try {
    await call<void>('/logout', { session: true });
  } finally {
    forgetCsrfToken();
  }
}

export type ReportReason = 'spam' | 'offensive' | 'false_information' | 'privacy' | 'conflict_of_interest' | 'other';

/** A signed-in member reports a published review (API.md 4.4). `409 DUPLICATE_OPEN_REPORT` if one is already open. */
export const reportReview = (reviewId: string, reasonCode: ReportReason, details?: string) =>
  call<{ report_id: string; state: string }>(`/api/v1/reviews/${encodeURIComponent(reviewId)}/reports`, {
    body: { reason_code: reasonCode, details: details || undefined },
    session: true,
  });

export const requestPasswordReset =(email: string, turnstileToken?: string | null) =>
  call<{ status: string }>('/password-reset/request', { body: { email, turnstile_token: turnstileToken ?? undefined } });

export const confirmPasswordReset = (tokenHash: string, newPassword: string) =>
  call<{ status: string }>('/password-reset/confirm', { body: { token_hash: tokenHash, new_password: newPassword } });
