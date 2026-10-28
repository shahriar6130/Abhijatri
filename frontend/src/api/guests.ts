/**
 * Guest identity and visit counting (Guest-Identity-and-Visits 3 and 4; API.md 5.14).
 *
 * Each browser has a guest tag such as `1C669-J0TDY`, derived from the guest scope secret. The tag,
 * the name and the visit dates live only on this device; the server never keeps a list of guests.
 * The browser reports at most one visit per Dhaka day with exactly `{ "first_visit": bool }`.
 *
 * The typed name is a 30-day session: it is kept while the guest keeps coming back and forgotten
 * after 30 days without a visit. The tag, the scope secret (and so receipts and duplicate-draft
 * recovery) and the visit dates stay, so a returning guest is never counted as new again.
 */

import { currentDisplayDate } from '../utils/format';
import { apiRequest } from './client';
import { getGuestScopeSecret, resetGuestScopeSecret } from './reviews';

const GUEST_NAME_KEY = 'abhijatri_guest_name';
const NAME_SEEN_KEY = 'abhijatri_guest_name_seen_on';
const FIRST_VISIT_KEY = 'abhijatri_first_visit_on';
const LAST_VISIT_KEY = 'abhijatri_last_visit_on';
/** Retired keys: read once to mark the browser as returning, then removed. */
const RETIRED_LAST_VISIT_KEY = 'abhijatri_guest_last_visit';
const RETIRED_NUMBER_KEY = 'abhijatri_guest_number';

/** Same limit as the review display name (API.md 5.15 `display_name`). */
export const GUEST_NAME_MAX = 80;
/** How long a typed guest name is remembered without a visit. */
export const GUEST_SESSION_DAYS = 30;

const TAG_PREFIX = 'abhijatri:guest-tag:v1\n';
const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked: behave as a first visit
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage blocked: the value lives only in memory for this visit
  }
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/**
 * `CrockfordBase32(SHA-256("abhijatri:guest-tag:v1\n" + secret))[first 50 bits]` as `XXXXX-XXXXX`.
 * Must match `backend/app/guest_tag.py` (test vector in guests.test.ts).
 */
export async function guestTag(scopeSecret: string): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest('SHA-256', new TextEncoder().encode(TAG_PREFIX + scopeSecret)),
  );
  let bits = 0n;
  for (const byte of digest.slice(0, 7)) bits = (bits << 8n) | BigInt(byte);
  bits >>= 6n; // keep the first 50 of 56 bits
  let tag = '';
  for (let index = 9; index >= 0; index -= 1) tag += CROCKFORD[Number((bits >> BigInt(5 * index)) & 31n)];
  return `${tag.slice(0, 5)}-${tag.slice(5)}`;
}

/** This browser's tag. Creates the scope secret on the first visit. */
export function loadGuestTag(): Promise<string> {
  return guestTag(getGuestScopeSecret());
}

/** Trimmed, NFC-normalised and at most 80 code points; null when nothing usable is left. */
export function normalizeGuestName(value: string): string | null {
  const normalized = value.normalize('NFC').trim();
  if (!normalized) return null;
  return [...normalized].slice(0, GUEST_NAME_MAX).join('').trim();
}

/** The remembered name, or null once 30 days have passed without a visit. */
export function loadGuestName(now: Date = new Date()): string | null {
  const stored = read(GUEST_NAME_KEY);
  if (!stored) return null;
  const seen = read(NAME_SEEN_KEY);
  if (seen && daysBetween(seen, currentDisplayDate(now)) > GUEST_SESSION_DAYS) {
    write(GUEST_NAME_KEY, null);
    write(NAME_SEEN_KEY, null);
    return null;
  }
  return normalizeGuestName(stored);
}

export function saveGuestName(name: string | null, now: Date = new Date()): void {
  write(GUEST_NAME_KEY, name);
  write(NAME_SEEN_KEY, name === null ? null : currentDisplayDate(now));
}

/** Keeps the name session alive: called on every visit. */
function touchGuestName(today: string): void {
  if (read(GUEST_NAME_KEY)) write(NAME_SEEN_KEY, today);
}

/**
 * Guest sign-out forgets the name only (Decisions 20 Oct 2026). The tag, the visit dates and the
 * scope secret stay, so the same browser is the same guest and is not counted as new again.
 */
export function signOutGuest(): void {
  saveGuestName(null);
}

/** "Start as a new guest": a new scope secret, so a new tag. Visit dates are kept (doc 3.3). */
export function startAsNewGuest(): Promise<string> {
  return guestTag(resetGuestScopeSecret());
}

/** Exactly `{ first_visit }`: nothing about the guest is sent (API.md 5.14). */
export function registerGuestVisit(firstVisit: boolean): Promise<void> {
  return apiRequest<void>('/api/v1/guest-visits', { method: 'POST', body: { first_visit: firstVisit } });
}

/** True when this browser has been counted before, under the current or a retired key. */
function isReturning(): boolean {
  return Boolean(read(FIRST_VISIT_KEY) || read(RETIRED_LAST_VISIT_KEY) || read(RETIRED_NUMBER_KEY));
}

/**
 * Counts this browser at most once per Dhaka day. Returns whether a request was sent. A failed
 * request leaves the dates untouched, so the next load tries again.
 */
export function recordDailyVisit(now: Date = new Date()): Promise<boolean> {
  // One request at a time: a second call (StrictMode double effect) shares the first one's result.
  inFlightVisit ??= sendDailyVisit(now).finally(() => {
    inFlightVisit = null;
  });
  return inFlightVisit;
}

let inFlightVisit: Promise<boolean> | null = null;

async function sendDailyVisit(now: Date): Promise<boolean> {
  const today = currentDisplayDate(now);
  touchGuestName(today);
  const lastVisit = read(LAST_VISIT_KEY) ?? read(RETIRED_LAST_VISIT_KEY);
  if (lastVisit === today) {
    migrateRetiredKeys(today);
    return false;
  }
  const firstVisit = !isReturning();
  await registerGuestVisit(firstVisit);
  write(LAST_VISIT_KEY, today);
  if (firstVisit || !read(FIRST_VISIT_KEY)) write(FIRST_VISIT_KEY, firstVisit ? today : lastVisit ?? today);
  migrateRetiredKeys(today);
  return true;
}

function migrateRetiredKeys(today: string): void {
  if (!read(RETIRED_LAST_VISIT_KEY) && !read(RETIRED_NUMBER_KEY)) return;
  if (!read(FIRST_VISIT_KEY)) write(FIRST_VISIT_KEY, read(RETIRED_LAST_VISIT_KEY) ?? today);
  if (!read(LAST_VISIT_KEY)) write(LAST_VISIT_KEY, read(RETIRED_LAST_VISIT_KEY) ?? today);
  write(RETIRED_LAST_VISIT_KEY, null);
  write(RETIRED_NUMBER_KEY, null);
}
