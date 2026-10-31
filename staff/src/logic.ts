/**
 * Pure helpers for the staff screens. Everything here only shapes what the interface offers; the
 * server re-checks every rule (Moderation spec 2.1: frontend checks are a convenience).
 */

import { StaffError } from './api';
import type { ReasonCatalogue, DecisionInput, Lang, ReportSubject } from './types';

export type Decision = DecisionInput['decision'];

/**
 * How stale a staff screen may be. The server turns an event into a notification within about 2 s
 * (`NOTIFY_POLL_SECONDS`), so these keep a new review or notice visible to a moderator within seconds
 * without a push channel. A hidden tab does not poll; it refreshes the moment it is shown again.
 */
export const QUEUE_POLL_MS = 5_000;
export const INBOX_POLL_MS = 10_000;

/** Calls `load` now, every `everyMs` while the tab is visible, and again whenever the tab or window regains focus. */
export function keepFresh(load: () => void, everyMs: number): () => void {
  load();
  const tick = () => {
    if (!document.hidden) load();
  };
  const timer = window.setInterval(tick, everyMs);
  document.addEventListener('visibilitychange', tick);
  window.addEventListener('focus', tick);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', tick);
    window.removeEventListener('focus', tick);
  };
}
export type ReportMove = 'in_review' | 'actioned' | 'dismissed';

/** Review status -> the decisions the server allows from it (mirrors `moderate_review`). */
export function decisionsFor(status: string): Decision[] {
  switch (status) {
    case 'PENDING':
    case 'UNDER_REVIEW':
      return ['PUBLISH', 'REJECT', 'REQUEST_CHANGES'];
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
    { code: 'privacy-pending', bn: 'গোপনীয়তার অভিযোগ, সিদ্ধান্তের অপেক্ষায়', en: 'Privacy complaint, pending a decision' },
    { code: 'safety-pending', bn: 'নিরাপত্তার অভিযোগ, সিদ্ধান্তের অপেক্ষায়', en: 'Safety complaint, pending a decision' },
  ],
  RESTORE: [
    { code: 'hidden-in-error', bn: 'ভুলে লুকানো হয়েছিল', en: 'Hidden in error' },
    { code: 'complaint-resolved', bn: 'অভিযোগের নিষ্পত্তি হয়েছে', en: 'Complaint resolved' },
  ],
  // The author reads this reason (the receipt and the review page show it), so no private detail belongs here.
  REQUEST_CHANGES: [
    { code: 'remove-personal-info', bn: 'ব্যক্তিগত তথ্য সরান', en: 'Remove personal information' },
    { code: 'add-detail', bn: 'আরও বিস্তারিত লিখুন', en: 'Add more detail' },
    { code: 'fix-language', bn: 'ভাষা বা বানান ঠিক করুন', en: 'Fix language or spelling' },
    { code: 'wrong-destination', bn: 'গন্তব্য বা মাস ঠিক করুন', en: 'Check the destination or month' },
  ],
};

/** Button text for a decision (the value sent to the server is the code itself). */
export const DECISION_LABEL: Record<Decision, { bn: string; en: string }> = {
  PUBLISH: { bn: 'প্রকাশ করুন', en: 'Publish' },
  REJECT: { bn: 'বাতিল করুন', en: 'Reject' },
  HIDE: { bn: 'লুকান', en: 'Hide' },
  RESTORE: { bn: 'ফিরিয়ে আনুন', en: 'Restore' },
  REQUEST_CHANGES: { bn: 'সংশোধন চান', en: 'Ask for changes' },
};

/** Report reasons (Review.md 5.4); the server sends the label too, this covers a build that has not loaded it. */
export const REPORT_REASONS: Record<string, { bn: string; en: string }> = {
  spam: { bn: 'স্প্যাম', en: 'Spam' },
  harassment: { bn: 'হয়রানি বা আপত্তিকর ভাষা', en: 'Harassment or offensive language' },
  offensive: { bn: 'হয়রানি বা আপত্তিকর ভাষা', en: 'Harassment or offensive language' }, // older reports
  false_information: { bn: 'ভুল তথ্য', en: 'False information' },
  privacy: { bn: 'ব্যক্তিগত তথ্য', en: 'Private information' },
  impersonation: { bn: 'ছদ্মবেশ', en: 'Impersonation' },
  safety_misinformation: { bn: 'নিরাপত্তা-সংক্রান্ত ভুল তথ্য', en: 'Safety misinformation' },
  copyright: { bn: 'কপিরাইট উদ্বেগ', en: 'Copyright concern' },
  conflict_of_interest: { bn: 'স্বার্থের দ্বন্দ্ব', en: 'Conflict of interest' },
  other: { bn: 'অন্যান্য', en: 'Other' },
  removal_request: { bn: 'অপসারণের অনুরোধ', en: 'Removal request' },
};

/** Which group of the server's reason catalogue each review decision uses (`GET /admin/reason-codes`). */
export const DECISION_GROUP: Record<Decision, string> = {
  PUBLISH: 'publish',
  REJECT: 'reject',
  HIDE: 'hide',
  RESTORE: 'restore',
  REQUEST_CHANGES: 'request_changes',
};

/** Why a rejected review can come back (superadmin only, within 30 days). */
export const REOPEN_REASONS: { code: string; bn: string; en: string }[] = [
  { code: 'rejected-in-error', bn: 'ভুলে বাতিল হয়েছিল', en: 'Rejected in error' },
  { code: 'author-corrected', bn: 'লেখক সংশোধন করেছেন', en: 'Author corrected the problem' },
];

/** The reasons the server accepts for a group: its own list once loaded, otherwise the built-in one. */
export function reasonsFor(
  catalogue: ReasonCatalogue | null,
  group: string,
  fallback: { code: string; bn: string; en: string }[],
): { code: string; bn: string; en: string }[] {
  const served = catalogue?.[group]?.reasons;
  return served && served.length > 0 ? served : fallback;
}

/** Time left to reopen a rejected review: whole days and hours, or null once the deadline has passed. */
export function recoveryLeft(deadline: string | null, now: number): { days: number; hours: number } | null {
  if (!deadline) return null;
  const ms = new Date(deadline).getTime() - now;
  if (Number.isNaN(ms) || ms <= 0) return null;
  const hours = Math.floor(ms / 3_600_000);
  return { days: Math.floor(hours / 24), hours: hours % 24 };
}

/** Only a superadmin may reopen a rejected review or export the audit log (the server decides; this hides the button). */
export const isSuperadmin = (role: string | null | undefined): boolean => role === 'superadmin';

/** The date inputs of the audit filter (a local day) as the inclusive start and exclusive end the API takes. */
export function auditRange(fromDay: string, toDay: string): { from?: string; to?: string } {
  const out: { from?: string; to?: string } = {};
  if (fromDay) out.from = new Date(`${fromDay}T00:00:00`).toISOString();
  if (toDay) {
    const end = new Date(`${toDay}T00:00:00`);
    end.setDate(end.getDate() + 1); // the chosen day is included
    out.to = end.toISOString();
  }
  return out;
}

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
    case 'REOPEN_WINDOW_CLOSED':
      return t('৩০ দিন পেরিয়ে গেছে বা লেখা মুছে ফেলা হয়েছে; রিভিউটি আর খোলা যাবে না।', 'The 30 days have passed or the text was removed; this review can no longer be reopened.');
    case 'INVALID_CURSOR':
      return t('পাতার চিহ্ন সঠিক নয়। তালিকা রিফ্রেশ করুন।', 'The page marker is not valid. Refresh the list.');
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
