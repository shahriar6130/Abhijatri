/**
 * Guest review lifecycle (Docs/api/API.md 5.1 to 5.4 and 5.8; Platform Foundation 13).
 *
 * Secrets rule: the guest scope secret and the receipt travel only in JSON bodies. They never go
 * into a URL, header, log, analytics event or error message.
 */

import type {
  CategoryRatings,
  ComfortTier,
  GuestReviewCreate,
  GuestReviewCreated,
  ReceiptStatus,
  ReviewCategory,
  ReviewFeed,
  ReviewLanguage,
  TravellerType,
} from '../types';
import { call } from './auth';
import { apiRequest } from './client';

/** Consent text version shown with the submission notice (API.md 5.2). */
export const CONSENT_VERSION = '2026-10-01';

/** Review.md 3.1, in display order. */
export const REVIEW_CATEGORIES: ReviewCategory[] = [
  'CLEANLINESS',
  'ACCESSIBILITY',
  'HOSPITALITY',
  'FOOD',
  'TRANSPORT',
  'SAFETY_PERCEPTION',
  'VALUE',
];

/**
 * The API rejects unknown fields (422 UNKNOWN_FIELD), so `category_ratings` is sent only once
 * the review service accepts it (R07). Set VITE_REVIEW_CATEGORY_RATINGS=true at that point.
 */
export const CATEGORY_RATINGS_ENABLED = import.meta.env.VITE_REVIEW_CATEGORY_RATINGS === 'true';

export interface GuestReviewDraft {
  destinationId: string;
  clientDraftId: string;
  receipt: string;
  guestScopeSecret: string;
  displayName: string;
  language: ReviewLanguage;
  travellerType: TravellerType;
  comfortTier: ComfortTier;
  /** `YYYY-MM` */
  visitMonth: string;
  title: string;
  note: string;
  overallRating: number;
  categoryRatings: CategoryRatings;
}

const BENGALI_LETTER = /[ঀ-৿]/gu;
const LATIN_LETTER = /[A-Za-zÀ-ɏ]/gu;
/** Share of the minority script above which a text counts as mixed. */
const MIXED_THRESHOLD = 0.2;

/**
 * Detects the review language from the script actually written, so a Bangla note typed in the
 * English interface is still labelled BN (Gantt R09: reviews remain in their submitted language).
 * Returns null when there are no letters yet. Banglish (Bangla in Latin letters) reads as EN by
 * script, so the reviewer can still override the choice.
 */
export function detectReviewLanguage(text: string): ReviewLanguage | null {
  const bengali = text.match(BENGALI_LETTER)?.length ?? 0;
  const latin = text.match(LATIN_LETTER)?.length ?? 0;
  const total = bengali + latin;
  if (total === 0) return null;
  if (Math.min(bengali, latin) / total >= MIXED_THRESHOLD) return 'MIXED';
  return bengali > latin ? 'BN' : 'EN';
}

/** Only rated categories (integers 1 to 5) are kept; "not applicable" is simply absent. */
export function cleanCategoryRatings(ratings: CategoryRatings): CategoryRatings {
  const cleaned: CategoryRatings = {};
  for (const category of REVIEW_CATEGORIES) {
    const value = ratings[category];
    if (Number.isInteger(value) && value! >= 1 && value! <= 5) cleaned[category] = value;
  }
  return cleaned;
}

/** Builds the POST /reviews/guest body (API.md 5.2) from the form state. Pure, for tests. */
export function buildGuestReviewPayload(
  draft: GuestReviewDraft,
  options: { sendCategoryRatings?: boolean } = {},
): GuestReviewCreate {
  const payload: GuestReviewCreate = {
    destination_id: draft.destinationId,
    client_draft_id: draft.clientDraftId,
    guest_scope_secret: draft.guestScopeSecret,
    receipt_secret: draft.receipt,
    guest_display_name: draft.displayName.trim().normalize('NFC'),
    language: draft.language,
    traveller_type: draft.travellerType,
    comfort_tier: draft.comfortTier,
    visit_month: `${draft.visitMonth}-01`,
    title: draft.title.trim(),
    body: draft.note.trim(),
    overall_rating: draft.overallRating,
    consent_version: CONSENT_VERSION,
  };
  const categories = cleanCategoryRatings(draft.categoryRatings);
  if ((options.sendCategoryRatings ?? CATEGORY_RATINGS_ENABLED) && Object.keys(categories).length > 0) {
    payload.category_ratings = categories;
  }
  return payload;
}

const RECEIPT_PATTERN = /^abr1_[A-Za-z0-9_-]{43}$/;
const GUEST_SCOPE_KEY = 'abhijatri_guest_scope';

function base64Url(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomBase64Url(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

/** PF 13.2: 32 bytes from crypto.getRandomValues, unpadded base64url, prefix `abr1_` (48 chars). */
export function generateReceipt(): string {
  return `abr1_${randomBase64Url(32)}`;
}

export function isReceiptFormat(value: string): boolean {
  return RECEIPT_PATTERN.test(value.trim());
}

/**
 * The guest scope secret is long-lived per device. It is the source of the guest tag
 * (Guest-Identity-and-Visits 3.1) and a supplemental abuse signal. PF 18.1 places it in IndexedDB;
 * until the offline draft store lands (R15) it is kept in localStorage. It never leaves the device
 * except in the review submission body. It is created on the first visit, so the badge exists at once.
 */
let inMemoryScope: string | null = null;

export function getGuestScopeSecret(): string {
  try {
    const stored = localStorage.getItem(GUEST_SCOPE_KEY);
    if (stored && stored.length >= 43) return stored;
    const fresh = randomBase64Url(48);
    localStorage.setItem(GUEST_SCOPE_KEY, fresh);
    return fresh;
  } catch {
    // Storage blocked: one scope (and so one tag) for the life of this tab.
    inMemoryScope ??= randomBase64Url(48);
    return inMemoryScope;
  }
}

/** "Start as a new guest": a new secret, therefore a new tag. Visit dates are kept. */
export function resetGuestScopeSecret(): string {
  const fresh = randomBase64Url(48);
  inMemoryScope = fresh;
  try {
    localStorage.setItem(GUEST_SCOPE_KEY, fresh);
  } catch {
    // storage blocked: the new scope lives only in this tab
  }
  return fresh;
}

export function getReviewFeed(
  destinationId: string,
  options: { after?: string | null; limit?: number; signal?: AbortSignal } = {},
): Promise<ReviewFeed> {
  return apiRequest<ReviewFeed>(`/api/v1/destinations/${encodeURIComponent(destinationId)}/reviews`, {
    params: { after: options.after, limit: options.limit },
    signal: options.signal,
  });
}

/**
 * 201 = created, 200 with `duplicate_recovered` = a retry of the same draft found the stored
 * review. The same `client_draft_id` and receipt must be reused on every retry of one draft.
 */
export function submitGuestReview(payload: GuestReviewCreate): Promise<GuestReviewCreated> {
  return apiRequest<GuestReviewCreated>('/api/v1/reviews/guest', {
    method: 'POST',
    body: payload,
  });
}

export function getReceiptStatus(reviewId: string, receiptSecret: string): Promise<ReceiptStatus> {
  return apiRequest<ReceiptStatus>('/api/v1/review-receipts/status', {
    method: 'POST',
    body: { review_id: reviewId, receipt_secret: receiptSecret },
  });
}

export function withdrawGuestReview(
  reviewId: string,
  receiptSecret: string,
  expectedVersion: number,
): Promise<ReceiptStatus> {
  return apiRequest<ReceiptStatus>(`/api/v1/reviews/${encodeURIComponent(reviewId)}/withdraw`, {
    method: 'POST',
    body: { receipt_secret: receiptSecret, expected_version: expectedVersion },
  });
}

/** A signed-in member's review (API.md 5.20): the guest scope, name and Turnstile token are not sent. */
export type MemberReviewCreate = Omit<GuestReviewCreate, 'guest_scope_secret' | 'guest_display_name' | 'turnstile_token'>;

export function submitMemberReview(payload: MemberReviewCreate): Promise<GuestReviewCreated> {
  return call<GuestReviewCreated>('/api/v1/reviews/member', { body: payload, session: true });
}

export interface MediaUpload {
  file: File;
  altText: string;
  caption: string;
}

/**
 * Attach one photo or video to the member's own pending review: ask for a one-time signed URL,
 * send the file straight to the private bucket, then let the server check and clean it.
 */
export async function uploadReviewMedia(reviewId: string, item: MediaUpload): Promise<void> {
  const base = `/api/v1/reviews/${encodeURIComponent(reviewId)}`;
  const intent = await call<{ media_id: string; upload_url: string }>(`${base}/media-intents`, {
    body: {
      content_type: item.file.type,
      size_bytes: item.file.size,
      alt_text: item.altText.trim(),
      caption: item.caption.trim() || undefined,
      ownership_declared: true,
    },
    session: true,
  });
  const put = await fetch(intent.upload_url, { method: 'PUT', body: item.file, headers: { 'Content-Type': item.file.type } });
  if (!put.ok) throw new Error(`upload failed (${put.status})`);
  await call(`${base}/media/${intent.media_id}/complete`, { session: true });
}
