/**
 * Staff API client (Docs/api/API.md 5.17 and 5.18).
 *
 * The session lives in HttpOnly cookies the page cannot read; every call sends them with
 * `credentials: 'include'`. Writes carry the synchronizer token from `GET /auth/csrf` (refetched once
 * if the server rejects it). Decisions carry an `Idempotency-Key` so a retry cannot apply twice.
 */

import type {
  AuditPage,
  DecidedReview,
  ReasonCatalogue,
  AuditItem,
  EnforcementCase,
  DecisionInput,
  Enrollment,
  QueueItem,
  ReportTransitionInput,
  Session,
  StaffMember,
  DeliveryDetail,
  DeliveryRow,
  InboxItem,
  OutboxRow,
  ReviewMedia,
  SuppressionRow,
  TemplateKey,
  TemplateVersion,
  Summary,
  Task,
  UserHit,
} from './types';

/**
 * Empty in the deployed build: the staff site forwards `/api/*` to the API itself (vercel.json), so the
 * session cookies belong to the staff site and are never cross-site.
 */
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
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  idempotencyKey?: string;
  /** False for the one write made before a session exists (sign-in); the API checks `Origin` instead. */
  csrf?: boolean;
}

async function send<T>(path: string, { method = 'GET', body, query, idempotencyKey, csrf = true }: CallOptions): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, globalThis.location?.origin ?? 'http://localhost');
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
  const method = options.method && options.method !== 'GET' ? options.method : 'POST';
  try {
    return await send<T>(path, { ...options, method });
  } catch (error) {
    if (error instanceof StaffError && error.code === 'CSRF_INVALID') {
      csrfToken = null;
      return send<T>(path, { ...options, method });
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

export interface StaffMediaItem extends ReviewMedia {
  state: 'pending' | 'approved' | 'rejected';
  review_id: string;
  review_status: string;
  destination_id: string;
  decided_at: string | null;
}

export const listMedia = (state?: 'pending' | 'approved' | 'rejected') =>
  send<{ items: StaffMediaItem[] }>('/api/v1/admin/media', { query: { state, limit: 50 } });

export const decideMedia = (mediaId: string, decision: 'approve' | 'reject', reasonCode: string) =>
  write<ReviewMedia & { state: string }>(`/api/v1/admin/media/${mediaId}/decision`, { body: { decision, reason_code: reasonCode } });

export const assignTask = (taskId: string, userId: string | null) =>
  write<Task>(`/api/v1/admin/tasks/${taskId}/assign`, { body: { user_id: userId } });

// ---- notifications (API.md 5.21) ----

export const getInbox = (cursor?: string | null) =>
  send<{ items: InboxItem[]; next_cursor: string | null; unread: number }>('/api/v1/notifications', { query: { limit: 30, cursor } });
export const markInboxRead = (id: string) => write<InboxItem>(`/api/v1/notifications/${id}`, { method: 'PATCH', body: { read: true } });
export const markInboxAllRead = () => write<{ unread: number }>('/api/v1/notifications/mark-all-read', {});

export const getDeliveries = (status?: string) =>
  send<{ items: DeliveryRow[]; counts: Record<string, number> }>('/api/v1/admin/notification-deliveries', { query: { status, limit: 50 } });
export const getDelivery = (id: string) => send<DeliveryDetail>(`/api/v1/admin/notification-deliveries/${id}`, {});
export const retryDelivery = (id: string, reason: string) => write<DeliveryRow>(`/api/v1/admin/notification-deliveries/${id}/retry`, { body: { reason } });
export const getOutbox = (status?: string) =>
  send<{ items: OutboxRow[]; counts: Record<string, number>; oldest_unprocessed_at: string | null }>('/api/v1/admin/notification-outbox', { query: { status, limit: 50 } });
export const getSuppressions = () => send<{ items: SuppressionRow[] }>('/api/v1/admin/notification-suppressions', {});
export const addSuppression = (email: string, reasonCode: string) =>
  write<SuppressionRow>('/api/v1/admin/notification-suppressions', { body: { email, channel: 'email', reason_code: reasonCode } });
export const removeSuppression = (id: string, removalReason: string) =>
  write<SuppressionRow>(`/api/v1/admin/notification-suppressions/${id}`, { method: 'DELETE', body: { removal_reason: removalReason } });
export const getTemplates = () => send<{ items: TemplateKey[] }>('/api/v1/admin/notification-templates', {});
export const getTemplateVersions = (key: string) => send<{ items: TemplateVersion[] }>(`/api/v1/admin/notification-templates/${key}/versions`, {});
export const createTemplateVersion = (key: string, input: { channel: 'in_app' | 'email'; locale: 'bn' | 'en'; title_template?: string; subject_template?: string; body_template: string }) =>
  write<TemplateVersion>(`/api/v1/admin/notification-templates/${key}/versions`, { body: input });
export const activateTemplateVersion = (key: string, version: number, channel: 'in_app' | 'email', locale: 'bn' | 'en') =>
  write<TemplateVersion>(`/api/v1/admin/notification-templates/${key}/versions/${version}/activate`, { body: { channel, locale } });
export const updateRule = (key: string, change: { priority?: string; email?: boolean; enabled?: boolean }) =>
  write<{ template_key: string; priority: string; email: boolean; enabled: boolean }>(`/api/v1/admin/notification-rules/${key}`, { method: 'PATCH', body: change });

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

export interface AuditFilters {
  action?: string;
  target_type?: string;
  target_id?: string;
  actor_role?: string;
  request_id?: string;
  /** Inclusive start and exclusive end, as ISO timestamps. */
  from?: string;
  to?: string;
}

export const getAuditEvents = (filters: AuditFilters, cursor?: string | null) =>
  send<AuditPage>('/api/v1/admin/audit-events', { query: { ...filters, cursor, limit: 50 } });

export const getAuditActions = () => send<{ actions: string[]; denied_prefix: string }>('/api/v1/admin/audit-events/actions', {});

/** The CSV for the same filters (superadmin). Returned as text; the caller offers it as a download. */
export async function exportAuditCsv(filters: AuditFilters): Promise<{ csv: string; rows: number; truncated: boolean }> {
  const url = new URL(`${API_BASE}/api/v1/admin/audit-events/export`, globalThis.location?.origin ?? 'http://localhost');
  for (const [key, value] of Object.entries(filters)) if (value) url.searchParams.set(key, String(value));
  let response: Response;
  try {
    response = await fetch(url, { credentials: 'include', cache: 'no-store', headers: { Accept: 'text/csv' } });
  } catch {
    throw new StaffError(0, 'NETWORK_ERROR');
  }
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    try {
      code = ((await response.json()) as { error?: { code?: string } }).error?.code ?? code;
    } catch {
      // not a JSON error body
    }
    throw new StaffError(response.status, code);
  }
  return { csv: await response.text(), rows: Number(response.headers.get('X-Row-Count') ?? 0), truncated: response.headers.get('X-Truncated') === 'true' };
}

export const getReasonCodes = () => send<{ groups: ReasonCatalogue }>('/api/v1/admin/reason-codes', {});

// ---- hide pending a decision, Rejected and Hidden lists, reopen (R11) ----

export const hidePending = (
  reportId: string,
  input: { expectedVersion: number; reasonCode: string; countsTowardRating: boolean; taskId: string; leaseToken: string },
) =>
  write<{ report_id: string; state: string; version: number; case_id: string; review_status: string; counted_rating: number | null }>(
    `/api/v1/admin/reports/${reportId}/hide-pending`,
    {
      body: {
        expected_version: input.expectedVersion,
        reason_code: input.reasonCode,
        counts_toward_rating: input.countsTowardRating,
        task_id: input.taskId,
        lease_token: input.leaseToken,
      },
    },
  );

export const getDecidedReviews = (status: 'REJECTED' | 'HIDDEN', after?: string | null) =>
  send<{ items: DecidedReview[]; next_cursor: string | null }>('/api/v1/admin/reviews', { query: { status, after, limit: 50 } });

export const reopenReview = (reviewId: string, input: { expectedVersion: number; reasonCode: string; note?: string }) =>
  write<{ review_id: string; status: string; version: number }>(`/api/v1/admin/reviews/${reviewId}/reopen`, {
    body: { expected_version: input.expectedVersion, reason_code: input.reasonCode, note: input.note || undefined },
  });

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