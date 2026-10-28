/**
 * Member calls for verification, appeals and notifications (API.md 5.19). Every call sends the
 * session cookie; writes carry the CSRF token through `call` in `auth.ts`.
 */

import type { AppNotification, AppealView, AppealableDecision, NotificationPreferences, VerificationCaseView } from '../types';
import { API_BASE_URL } from './client';
import { call } from './auth';

export const getMyVerification = () =>
  call<{ verified_member: boolean; case: VerificationCaseView | null }>('/api/v1/verifications/mine', { method: 'GET' });

export const requestVerification = (statement: string) =>
  call<VerificationCaseView>('/api/v1/verifications', { body: { statement: statement || undefined }, session: true });

export const respondToVerification = (caseId: string, statement: string) =>
  call<VerificationCaseView>(`/api/v1/verifications/${caseId}/respond`, { body: { statement }, session: true });

export const withdrawVerification = (caseId: string) => call<VerificationCaseView>(`/api/v1/verifications/${caseId}/withdraw`, { session: true });

export const EVIDENCE_TYPES = ['image/jpeg', 'image/png', 'application/pdf'];
export const EVIDENCE_MAX_BYTES = 5 * 1024 * 1024;

/**
 * Upload one evidence file: ask the API for a one-time signed URL, send the file straight to the
 * private bucket, then tell the API it is there. The API never sees the bytes and the browser never
 * holds a storage key.
 */
export async function uploadEvidence(caseId: string, file: File): Promise<void> {
  const intent = await call<{ evidence_id: string; upload_url: string }>(`/api/v1/verifications/${caseId}/evidence`, {
    body: { content_type: file.type, size_bytes: file.size },
    session: true,
  });
  const put = await fetch(intent.upload_url, { method: 'PUT', body: file, headers: { 'Content-Type': file.type } });
  if (!put.ok) throw new Error(`upload failed (${put.status})`);
  await call(`/api/v1/verifications/${caseId}/evidence/${intent.evidence_id}/complete`, { session: true });
}

export const getMyAppeals = () => call<{ appeals: AppealView[]; appealable: AppealableDecision[] }>('/api/v1/appeals/mine', { method: 'GET' });

export const submitAppeal = (targetType: AppealableDecision['target_type'], targetId: string, reason: string) =>
  call<AppealView>('/api/v1/appeals', { body: { target_type: targetType, target_id: targetId, reason }, session: true });

export const withdrawAppeal = (appealId: string) => call<AppealView>(`/api/v1/appeals/${appealId}/withdraw`, { session: true });

/** Notification inbox (API.md 5.21). The inbox is the source of truth; the live stream is only a hint. */
export interface NotificationPage {
  items: AppNotification[];
  next_cursor: string | null;
  unread: number;
}

export function notificationsQuery(options: { cursor?: string | null; archived?: boolean; unreadOnly?: boolean; limit?: number } = {}): string {
  const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
  if (options.cursor) params.set('cursor', options.cursor);
  if (options.archived) params.set('archived', 'true');
  if (options.unreadOnly) params.set('unread_only', 'true');
  return `/api/v1/notifications?${params.toString()}`;
}

export const getNotifications = (options: Parameters<typeof notificationsQuery>[0] = {}) =>
  call<NotificationPage>(notificationsQuery(options), { method: 'GET' });

export const getUnreadCount = () => call<{ unread: number }>('/api/v1/notifications/unread-count', { method: 'GET' });

export const updateNotification = (id: string, change: { read?: boolean; archived?: boolean }) =>
  call<AppNotification & { unread: number }>(`/api/v1/notifications/${encodeURIComponent(id)}`, { method: 'PATCH', body: change, session: true });

export const markRead = (id: string) => updateNotification(id, { read: true });

export const markAllRead = () => call<{ unread: number }>('/api/v1/notifications/mark-all-read', { session: true });

export const getNotificationPreferences = () => call<NotificationPreferences>('/api/v1/notification-preferences', { method: 'GET' });

/** Sends only the three editable fields: the API refuses unknown ones (such as `always_immediate`). */
export const saveNotificationPreferences = (prefs: Pick<NotificationPreferences, 'standard_email_mode' | 'digest_timezone' | 'digest_local_time'>) =>
  call<NotificationPreferences>('/api/v1/notification-preferences', {
    method: 'PUT',
    body: { standard_email_mode: prefs.standard_email_mode, digest_timezone: prefs.digest_timezone, digest_local_time: prefs.digest_local_time },
    session: true,
  });

export interface StreamHandlers {
  onUnread: (unread: number) => void;
  onNotification: (item: AppNotification, unread: number) => void;
  /** The stream dropped; `EventSource` retries by itself. */
  onDisconnect?: () => void;
  /** The stream is back: refetch the inbox, because events sent while away are not replayed. */
  onReconnect?: () => void;
}

/** Live notifications over Server-Sent Events; returns a function that closes the stream. */
export function subscribeToNotifications(handlers: StreamHandlers): () => void {
  if (typeof EventSource === 'undefined') return () => undefined;
  const source = new EventSource(`${API_BASE_URL}/api/v1/notifications/stream`, { withCredentials: true });
  let dropped = false;
  source.addEventListener('open', () => {
    if (dropped) handlers.onReconnect?.();
    dropped = false;
  });
  source.addEventListener('error', () => {
    if (!dropped) handlers.onDisconnect?.();
    dropped = true;
  });
  source.addEventListener('unread', (event) => handlers.onUnread((JSON.parse((event as MessageEvent).data) as { unread: number }).unread));
  source.addEventListener('notification', (event) => {
    const data = JSON.parse((event as MessageEvent).data) as { notification: AppNotification; unread: number };
    handlers.onNotification(data.notification, data.unread);
  });
  return () => source.close();
}
