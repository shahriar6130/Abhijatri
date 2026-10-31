import { ApiError, NETWORK_ERROR, apiRequest } from './client';
import { call } from './auth';

/**
 * Reporting a published review (Review.md 5.4, API.md 5.22). Members report with their session; visitors report
 * anonymously with a Turnstile token. The answer to an anonymous report is always the same "received", whether or
 * not the review exists or was already reported, so the screens never say more than that.
 */

export const REPORT_REASONS = [
  { value: 'spam', bn: 'স্প্যাম', en: 'Spam' },
  { value: 'harassment', bn: 'হয়রানি বা আপত্তিকর ভাষা', en: 'Harassment or offensive language' },
  { value: 'false_information', bn: 'ভুল তথ্য', en: 'False information' },
  { value: 'privacy', bn: 'ব্যক্তিগত তথ্য', en: 'Private information' },
  { value: 'impersonation', bn: 'ছদ্মবেশ', en: 'Impersonation' },
  { value: 'safety_misinformation', bn: 'নিরাপত্তা-সংক্রান্ত ভুল তথ্য', en: 'Safety misinformation' },
  { value: 'copyright', bn: 'কপিরাইট উদ্বেগ', en: 'Copyright concern' },
  { value: 'conflict_of_interest', bn: 'স্বার্থের দ্বন্দ্ব', en: 'Conflict of interest' },
  { value: 'other', bn: 'অন্যান্য', en: 'Other' },
] as const;

export type ReportReason = (typeof REPORT_REASONS)[number]['value'];

export const REPORT_DETAILS_MAX = 1000;
export const CONTACT_MAX = 200;
export const REMOVAL_STATEMENT_MIN = 10;

/** The same shape the server accepts: an email address or a phone number. */
const EMAIL = /^[^@\s]{1,64}@[^@\s]{1,150}\.[^@\s]{2,30}$/;
const PHONE = /^\+?\(?[0-9][0-9 \-()]{6,24}[0-9]$/;

export type ContactProblem = 'REQUIRED' | 'INVALID' | 'TOO_LONG' | null;

export function contactProblem(value: string, required: boolean): ContactProblem {
  const text = value.trim();
  if (!text) return required ? 'REQUIRED' : null;
  if (text.length > CONTACT_MAX) return 'TOO_LONG';
  return EMAIL.test(text) || PHONE.test(text) ? null : 'INVALID';
}

/** A review id as a person pastes it; the API wants a UUID. */
export const isReviewId = (value: string): boolean => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.trim());

/** A signed-in member reports a review. `409 DUPLICATE_OPEN_REPORT` when one of theirs is already open. */
export const reportReview = (reviewId: string, reasonCode: ReportReason, details?: string) =>
  call<{ report_id: string; state: string }>(`/api/v1/reviews/${encodeURIComponent(reviewId)}/reports`, {
    body: { reason_code: reasonCode, details: details || undefined },
    session: true,
  });

/** A visitor reports a review. No cookie is sent; the Turnstile token proves a person is there. */
export const reportReviewAnonymously = (input: { reviewId: string; reasonCode: ReportReason; details?: string; contact?: string; turnstileToken?: string | null }) =>
  apiRequest<{ received: boolean }>('/api/v1/public/review-reports', {
    method: 'POST',
    body: {
      review_id: input.reviewId.trim(),
      reason_code: input.reasonCode,
      details: input.details?.trim() || undefined,
      contact: input.contact?.trim() || undefined,
      turnstile_token: input.turnstileToken ?? undefined,
    },
  });

/** The author lost the receipt and asks for the review to be removed; a moderator checks ownership by the contact. */
export const requestRemoval = (input: { reviewId: string; statement: string; contact: string; turnstileToken?: string | null }) =>
  apiRequest<{ received: boolean }>('/api/v1/public/removal-requests', {
    method: 'POST',
    body: {
      review_id: input.reviewId.trim(),
      statement: input.statement.trim(),
      contact: input.contact.trim(),
      turnstile_token: input.turnstileToken ?? undefined,
    },
  });

export interface MyReport {
  id: string;
  review_id: string;
  reason_code: string;
  state: 'open' | 'in_review' | 'actioned' | 'dismissed';
  created_at: string;
}

export const getMyReports = (cursor?: string | null) =>
  call<{ items: MyReport[]; next_cursor: string | null }>(`/api/v1/reports/mine${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`, {
    method: 'GET',
    session: true,
  });

export type ReportFailure = 'duplicate' | 'rate_limited' | 'restricted' | 'challenge' | 'not_allowed' | 'invalid' | 'offline' | 'other';

/** What went wrong, as a kind the screen turns into a sentence in the reader's language. */
export function reportFailure(error: unknown): ReportFailure {
  if (!(error instanceof ApiError)) return 'other';
  switch (error.code) {
    case 'DUPLICATE_OPEN_REPORT':
      return 'duplicate';
    case 'RATE_LIMITED':
      return 'rate_limited';
    case 'ACCOUNT_RESTRICTED':
    case 'ACCOUNT_DISABLED':
      return 'restricted';
    case 'CHALLENGE_FAILED':
      return 'challenge';
    case 'FORBIDDEN':
      return 'not_allowed';
    case 'VALIDATION_FAILED':
      return 'invalid';
    case NETWORK_ERROR:
      return 'offline';
    default:
      return 'other';
  }
}
