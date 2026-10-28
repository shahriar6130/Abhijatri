/**
 * Member calls for verification, appeals and notifications (API.md 5.19). Every call sends the
 * session cookie; writes carry the CSRF token through `call` in `auth.ts`.
 */

import type { AppNotification, AppealView, AppealableDecision, VerificationCaseView } from '../types';
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

export const getNotifications = () => call<{ items: AppNotification[]; unread: number }>('/api/v1/notifications', { method: 'GET' });

export const markRead = (id: string) => call<{ unread: number }>(`/api/v1/notifications/${id}/read`, { session: true });

export const markAllRead = () => call<{ unread: number }>('/api/v1/notifications/read-all', { session: true });

/** Live notifications over Server-Sent Events; returns a function that closes the stream. */
export function subscribeToNotifications(onUnread: (unread: number) => void, onNotification: (item: AppNotification, unread: number) => void): () => void {
  if (typeof EventSource === 'undefined') return () => undefined;
  const source = new EventSource(`${API_BASE_URL}/api/v1/notifications/stream`, { withCredentials: true });
  source.addEventListener('unread', (event) => onUnread((JSON.parse((event as MessageEvent).data) as { unread: number }).unread));
  source.addEventListener('notification', (event) => {
    const data = JSON.parse((event as MessageEvent).data) as { notification: AppNotification; unread: number };
    onNotification(data.notification, data.unread);
  });
  return () => source.close();
}
