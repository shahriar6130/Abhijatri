/**
 * Pure helpers for the staff screens. Everything here only shapes what the interface offers; the
 * server re-checks every rule (Moderation spec 2.1: frontend checks are a convenience).
 */

import { StaffError } from './api';
import type { DecisionInput, Lang, ReportSubject } from './types';

export type Decision = DecisionInput['decision'];
export type ReportMove = 'in_review' | 'actioned' | 'dismissed';

/** Review status -> the decisions the server allows from it (mirrors `moderate_review`). */
export function decisionsFor(status: string): Decision[] {
  switch (status) {
    case 'PENDING':
    case 'UNDER_REVIEW':
      return ['PUBLISH', 'REJECT'];
    case 'PUBLISHED':
      return ['HIDE'];
    case 'HIDDEN':
      return ['RESTORE'];
    default:
      return [];
  }
}

/** Report state -> the moves the server allows from it (spec 7, `REPORT_TRANSITIONS`). */
export function reportMoves(state: ReportSubject['state']): ReportMove[] {
  if (state === 'open') return ['in_review', 'actioned', 'dismissed'];
  if (state === 'in_review') return ['actioned', 'dismissed'];
  return [];
}

export type VerificationMove = 'in_review' | 'needs_clarification' | 'approved' | 'rejected' | 'escalated';

/** Verification state -> moves a staff member of this role may offer (mirrors `VERIFICATION_TRANSITIONS`). */
export function verificationMoves(state: string, role: 'moderator' | 'superadmin'): VerificationMove[] {
  switch (state) {
    case 'submitted':
      return ['in_review', 'escalated'];
    case 'in_review':
      return ['approved', 'rejected', 'needs_clarification', 'escalated'];
    case 'escalated':
      return role === 'superadmin' ? ['approved', 'rejected'] : [];
    default:
      return [];
  }
}

/** Enforcement case state -> actions offered (mirrors `ENFORCEMENT_ACTIONS`). */
export function enforcementActions(state: string): ('remove' | 'restore' | 'close')[] {
  if (state === 'taken_down') return ['remove', 'restore'];
  if (state === 'removed') return ['restore'];
  if (state === 'open') return ['close'];
  return [];
}

export const REASONS: Record<Decision,{ code: string; bn: string; en: string }[]> = {
  PUBLISH: [{ code: 'meets-policy', bn: 'নীতিমালা মেনে চলে', en: 'Meets the policy' }],
  REJECT: [
    { code: 'spam', bn: 'স্প্যাম', en: 'Spam' },
    { code: 'offensive', bn: 'আপত্তিকর ভাষা', en: 'Offensive language' },
    { code: 'off-topic', bn: 'বিষয়বহির্ভূত', en: 'Off topic' },
    { code: 'privacy', bn: 'ব্যক্তিগত তথ্য', en: 'Personal information' },
  ],
  HIDE: [
    { code: 'reported-spam', bn: 'রিপোর্ট করা স্প্যাম', en: 'Reported spam' },
    { code: 'policy-violation', bn: 'নীতিমালা লঙ্ঘন', en: 'Policy violation' },
    { code: 'legal-request', bn: 'আইনি অনুরোধ', en: 'Legal request' },
  ],
  RESTORE: [{ code: 'hidden-in-error', bn: 'ভুলে লুকানো হয়েছিল', en: 'Hidden in error' }],
};

export const REPORT_REASONS: Record<string, { bn: string; en: string }> = {
  spam: { bn: 'স্প্যাম', en: 'Spam' },
  offensive: { bn: 'আপত্তিকর', en: 'Offensive' },
  false_information: { bn: 'ভুল তথ্য', en: 'False information' },
  privacy: { bn: 'গোপনীয়তা', en: 'Privacy' },
  conflict_of_interest: { bn: 'স্বার্থের দ্বন্দ্ব', en: 'Conflict of interest' },
  other: { bn: 'অন্যান্য', en: 'Other' },
};

export const REPORT_RESOLUTIONS: Record<ReportMove, { code: string; bn: string; en: string }> = {
  in_review: { code: 'looking', bn: 'পর্যালোচনা শুরু', en: 'Start review' },
  actioned: { code: 'report-confirmed', bn: 'ব্যবস্থা নেওয়া হয়েছে', en: 'Action taken' },
  dismissed: { code: 'report-dismissed', bn: 'প্রত্যাখ্যাত', en: 'Dismiss' },
};

/** Whole seconds until `iso`, never negative; null without a lease. */
export function secondsLeft(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.parse(iso) - now) / 1000));
}

export function formatCountdown(seconds: number | null): string {
  if (seconds === null) return '—';
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

/** One key per decision attempt: a retry of the same attempt reuses it, a new attempt gets a new one. */
export function newIdempotencyKey(): string {
  return `ui-${crypto.randomUUID()}`;
}

/**
 * The authenticator QR as an image source. Supabase returns an SVG inside a `data:` URL without
 * encoding it, which browsers refuse to draw; it is re-encoded here. Anything else is not trusted
 * as an image source and yields null (the secret key under the QR still works).
 */
export function qrImageSource(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const start = raw.indexOf('<svg');
  // Either a bare SVG document (what the API returns today) or an unencoded `data:image/svg+xml` URL.
  if (start !== -1 && (raw.startsWith('<') || raw.startsWith('data:image/svg+xml'))) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(raw.slice(start))}`;
  }
  return /^data:image\/(png|svg\+xml);base64,[A-Za-z0-9+/=]+$/.test(raw) ? raw : null;
}

/** Errors after which the screen must reload the task from the server. */
export const RELOAD_CODES = new Set(['LEASE_LOST', 'REVIEW_VERSION_CONFLICT', 'TASK_NOT_AVAILABLE', 'NOT_FOUND']);

export function errorText(error: unknown, lang: Lang): string {
  const t = (bn: string, en: string) => (lang === 'bn' ? bn : en);
  if (!(error instanceof StaffError)) return t('একটি ত্রুটি ঘটেছে।', 'Something went wrong.');
  switch (error.code) {
    case 'NETWORK_ERROR':
      return t('API-তে পৌঁছানো যায়নি। API চালু আছে কি না এবং CORS_ALLOWED_ORIGINS-এ এই ঠিকানা আছে কি না দেখুন।', 'Could not reach the API. Check that it is running and that CORS_ALLOWED_ORIGINS lists this address.');
    case 'INVALID_CREDENTIALS':
      return t('ইমেইল, পাসওয়ার্ড বা কোড সঠিক নয়।', 'The email, password or code is not correct.');
    case 'EMAIL_NOT_VERIFIED':
      return t('আগে ইমেইল যাচাই করুন।', 'Verify the email address first.');
    case 'ACCOUNT_DISABLED':
      return t('এই অ্যাকাউন্টটি বন্ধ।', 'This account is disabled.');
    case 'RATE_LIMITED':
      return t('অনেকবার চেষ্টা হয়েছে। একটু পরে আবার চেষ্টা করুন।', 'Too many attempts. Try again in a while.');
    case 'AUTH_REQUIRED':
      return t('সেশন শেষ। আবার সাইন ইন করুন।', 'Your session ended. Sign in again.');
    case 'MFA_REQUIRED':
      return t('এই কাজের জন্য অথেনটিকেটর কোড দিয়ে যাচাই করতে হবে।', 'This needs a code from your authenticator app.');
    case 'REAUTH_REQUIRED':
      return t('এই কাজের আগে আবার পাসওয়ার্ড দিয়ে যাচাই করুন।', 'Confirm your password again before this action.');
    case 'FORBIDDEN':
      return t('এই কাজের অনুমতি আপনার নেই (বা কাজটি উপরের স্তরে পাঠানো হয়েছে)।', 'You are not allowed to do this (or it was escalated above your role).');
    case 'NOT_FOUND':
      return t('খুঁজে পাওয়া যায়নি। তালিকা রিফ্রেশ করুন।', 'Not found. Refresh the list.');
    case 'LEASE_LOST':
      return t('এই কাজের দখল শেষ হয়েছে বা অন্যের হাতে গেছে। রিলোড করুন।', 'Your claim on this task ended or moved to someone else. Reload.');
    case 'TASK_NOT_AVAILABLE':
      return t('কাজটি এখন অন্য কেউ করছেন।', 'Someone else is working on this task right now.');
    case 'REVIEW_VERSION_CONFLICT':
      return t('এই বিষয়টি ইতিমধ্যে পরিবর্তিত হয়েছে। রিলোড করুন।', 'This item has already changed. Reload.');
    case 'TRANSITION_NOT_ALLOWED':
      return t('বর্তমান অবস্থা থেকে এই পরিবর্তন অনুমোদিত নয়।', 'That change is not allowed from the current state.');
    case 'IDEMPOTENCY_KEY_REUSED':
      return t('একই অনুরোধ-কী ভিন্ন তথ্যে ব্যবহার হয়েছে।', 'The same request key was used with different data.');
    case 'LAST_SUPERADMIN':
      return t('শেষ সুপারঅ্যাডমিনকে সরানো যাবে না।', 'The last superadmin cannot be removed.');
    case 'CSRF_INVALID':
      return t('অনুরোধটি যাচাই করা যায়নি। পাতা রিফ্রেশ করুন।', 'The request could not be verified. Refresh the page.');
    case 'VALIDATION_FAILED':
      return t('তথ্য সঠিক নয়। ফর্ম দেখুন।', 'The data is not valid. Check the form.');
    case 'SERVICE_UNAVAILABLE':
      return t('সেবাটি এখন পাওয়া যাচ্ছে না।', 'The service is unavailable right now.');
    default:
      return t(`ত্রুটি: ${error.code}`, `Error: ${error.code}`);
  }
}
