/**
 * Staff API client (Docs/api/API.md 5.17 and 5.18).
 *
 * The session lives in HttpOnly cookies the page cannot read; every call sends them with
 * `credentials: 'include'`. Writes carry the synchronizer token from `GET /auth/csrf` (refetched once
 * if the server rejects it). Decisions carry an `Idempotency-Key` so a retry cannot apply twice.
 */

import type {
  AuditItem,
  EnforcementCase,
  DecisionInput,
  Enrollment,
  QueueItem,
  ReportTransitionInput,
  Session,
  StaffMember,
  Summary,
  Task,
  UserHit,
} from './types';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '');

export class StaffError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly fieldErrors: { field: string; code: string }[] = [],
  ) {
    super(code);
  }
}

let csrfToken: string | null = null;
export const setCsrfToken = (token: string | null): void => {
  csrfToken = token;
};

interface CallOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  idempotencyKey?: string;
  /** False for the one write made before a session exists (sign-in); the API checks `Origin` instead. */
  csrf?: boolean;
}

async function send<T>(path: string, { method = 'GET', body, query, idempotencyKey, csrf = true }: CallOptions): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrf) {
    if (csrfToken === null) csrfToken = (await send<{ csrf_token: string }>('/api/v1/auth/csrf', {})).csrf_token;
    headers['X-CSRF-Token'] = csrfToken;
  }
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      credentials: 'include',
      cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new StaffError(0, 'NETWORK_ERROR');
  }
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let fieldErrors: { field: string; code: string }[] = [];
    try {
      const parsed = (await response.json()) as { error?: { code?: string; field_errors?: { field: string; code: string }[] } };
      code = parsed.error?.code ?? code;
      fieldErrors = parsed.error?.field_errors ?? [];
    } catch {
      // not a JSON error body
    }
    throw new StaffError(response.status, code, fieldErrors);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A write that retries once with a fresh CSRF token if the server says the token is stale. */
async function write<T>(path: string, options: CallOptions): Promise<T> {
  try {
    return await send<T>(path, { ...options, method: 'POST' });
  } catch (error) {
    if (error instanceof StaffError && error.code === 'CSRF_INVALID') {
      csrfToken = null;
      return send<T>(path, { ...options, method: 'POST' });
    }
    throw error;
  }
}

// ---- sign-in ----

export const getSession = () => send<Session>('/api/v1/auth/session', {});

export async function login(email: string, password: string): Promise<Session> {
  const session = await write<Session>('/api/v1/auth/login', { body: { email, password }, csrf: false });
  csrfToken = null;
  return session;
}

export async function logout(): Promise<void> {
  try {
    await write<void>('/api/v1/auth/logout', {});
  } finally {
    csrfToken = null;
  }
}

export const mfaEnroll = () => write<Enrollment>('/api/v1/auth/mfa/enroll', {});

export async function mfaVerify(factorId: string, code: string): Promise<void> {
  const answer = await write<{ csrf_token: string }>('/api/v1/auth/mfa/verify', { body: { factor_id: factorId, code } });
  csrfToken = answer.csrf_token;
}

export async function reauth(password: string, code?: string): Promise<void> {
  const answer = await write<{ csrf_token: string }>('/api/v1/auth/reauth', { body: { password, code: code || undefined } });
  csrfToken = answer.csrf_token;
}

// ---- queue and claims ----

export const getQueue = (taskType?: string) =>
  send<{ items: QueueItem[]; generated_at: string }>('/api/v1/admin/queue', { query: { task_type: taskType, limit: 100 } });

export const claimTask = (id: string) => write<Task>(`/api/v1/admin/tasks/${id}/claim`, {});
export const heartbeatTask = (id: string, leaseToken: string) => write<Task>(`/api/v1/admin/tasks/${id}/heartbeat`, { body: { lease_token: leaseToken } });
export const releaseTask = (id: string, leaseToken: string) => write<Task>(`/api/v1/admin/tasks/${id}/release`, { body: { lease_token: leaseToken } });
export const escalateTask = (id: string, leaseToken: string, reason: string) =>
  write<Task>(`/api/v1/admin/tasks/${id}/escalate`, { body: { lease_token: leaseToken, reason } });

export const decide = (reviewId: string, input: DecisionInput, idempotencyKey: string) =>
  write<{ review_id: string; status: string; version: number }>(`/api/v1/admin/submissions/${reviewId}/moderation-actions`, {
    body: {
      task_id: input.taskId,
      lease_token: input.leaseToken,
      expected_version: input.expectedVersion,
      decision: input.decision,
      reason_code: input.reasonCode,
      note: input.note || undefined,
      ...(input.rejectedMediaIds?.length ? { rejected_media_ids: input.rejectedMediaIds } : {}),
    },
    idempotencyKey,
  });

/** A five-minute link to a checked photo or video of a review in the queue. */
export const reviewMediaUrl = (reviewId: string, mediaId: string) =>
  write<{ url: string; expires_in: number }>(`/api/v1/admin/submissions/${reviewId}/media/${mediaId}/url`, {});

export const transitionReport = (reportId: string, input: ReportTransitionInput) =>
  write<{ report_id: string; state: string; version: number }>(`/api/v1/admin/reports/${reportId}/transition`, {
    body: {
      task_id: input.taskId,
      lease_token: input.leaseToken,
      expected_version: input.expectedVersion,
      to: input.to,
      reason_code: input.reasonCode,
      note: input.note || undefined,
    },
  });

// ---- audit, staff, monitoring ----

export const getAuditEvents = (filters: { action?: string; target_type?: string; target_id?: string; before?: string }) =>
  send<{ items: AuditItem[]; next_before: string | null }>('/api/v1/admin/audit-events', { query: { ...filters, limit: 50 } });

export const getAuditEvent = (id: string) => send<AuditItem>(`/api/v1/admin/audit-events/${id}`, {});
export const getStaff = () => send<{ items: StaffMember[] }>('/api/v1/admin/staff', {});
export const searchUsers = (q: string) => send<{ items: UserHit[] }>('/api/v1/admin/users', { query: { q } });
export const setRole = (userId: string, role: 'moderator' | 'superadmin' | null, reason: string) =>
  write<{ user_id: string; role: string | null }>(`/api/v1/admin/staff/${userId}/role`, { body: { role, reason } });
export const getSummary = () => send<Summary>('/api/v1/admin/monitoring/summary', {});

// ---- verification, enforcement, appeals ----

export const transitionVerification = (
  caseId: string,
  input: { to: string; expectedVersion: number; reasonCode: string; note?: string; taskId: string; leaseToken: string },
) =>
  write<{ case_id: string; state: string; version: number }>(`/api/v1/admin/verification-cases/${caseId}/transition`, {
    body: { to: input.to, expected_version: input.expectedVersion, reason_code: input.reasonCode, note: input.note || undefined, task_id: input.taskId, lease_token: input.leaseToken },
  });

export const evidenceUrl = (caseId: string, evidenceId: string) =>
  write<{ url: string; expires_in: number; content_type: string }>(`/api/v1/admin/verification-cases/${caseId}/evidence/${evidenceId}/url`, {});

export const decideAppeal = (appealId: string, input: { outcome: 'upheld' | 'overturned'; expectedVersion: number; note: string; taskId: string; leaseToken: string }) =>
  write<{ appeal_id: string; state: string; version: number }>(`/api/v1/admin/appeals/${appealId}/decision`, {
    body: { outcome: input.outcome, expected_version: input.expectedVersion, note: input.note, task_id: input.taskId, lease_token: input.leaseToken },
  });

export const getEnforcementCases = (state?: string) => send<{ items: EnforcementCase[] }>('/api/v1/admin/enforcement-cases', { query: { state } });

export interface OpenEnforcementInput {
  review_id?: string;
  user_id?: string;
  reason_code: string;
  note?: string;
  emergency: boolean;
  counts_toward_rating: boolean;
  sanction?: { kind: 'warning' | 'posting_restriction' | 'suspension'; ends_at?: string; review_on?: string };
}

export const openEnforcement = (input: OpenEnforcementInput) => write<EnforcementCase>('/api/v1/admin/enforcement-cases', { body: input });

export const enforcementAction = (
  caseId: string,
  input: { action: 'remove' | 'restore' | 'close' | 'reverse_sanction'; expected_version: number; reason_code: string; note?: string; counts_toward_rating?: boolean; sanction_id?: string },
) => write<{ case_id: string; state: string; version: number }>(`/api/v1/admin/enforcement-cases/${caseId}/actions`, { body: input });