import { describe, expect, it } from 'vitest';
import type { PublicReview, ReviewDetail } from '../types';
import {
  APPEAL_MAX,
  APPEAL_MIN,
  DEFAULT_FILTERS,
  appealStatementProblem,
  applyReviewFilters,
  canAppealRejection,
  canEdit,
  canWithdraw,
  diffEdit,
  filtersActive,
  hasChanges,
  valuesFromDetail,
  type ReviewFilters,
} from './reviewAuthor';

const detail = (overrides: Partial<ReviewDetail> = {}): ReviewDetail => ({
  id: 'r1',
  destination_id: 'd1',
  author_type: 'MEMBER',
  status: 'PENDING',
  version: 2,
  rating_eligibility: 'NOT_EVALUATED',
  language: 'EN',
  traveller_type: 'SOLO',
  comfort_tier: 'STANDARD',
  visit_month: '2026-09-01',
  title: 'Clouds over the hills',
  body: 'We watched the clouds roll over the hills at sunrise.',
  overall_rating: 4,
  category_ratings: { FOOD: 4, SAFETY_PERCEPTION: 5 },
  consent_version: '2026-10-01',
  created_at: '2026-10-01T00:00:00Z',
  published_at: null,
  withdrawn_at: null,
  decision_reason: null,
  appeal_deadline: null,
  appeal_state: null,
  revisions: [],
  media: [],
  ...overrides,
});

describe('what an author may do in each state (Review.md 5.1, 5.2)', () => {
  it('edits only PENDING and CHANGES_REQUESTED', () => {
    expect(canEdit('PENDING')).toBe(true);
    expect(canEdit('CHANGES_REQUESTED')).toBe(true);
    for (const status of ['UNDER_REVIEW', 'PUBLISHED', 'HIDDEN', 'REJECTED', 'WITHDRAWN', 'DELETED'] as const) expect(canEdit(status)).toBe(false);
  });

  it('withdraws until the review is already withdrawn, deleted or rejected', () => {
    for (const status of ['PENDING', 'UNDER_REVIEW', 'CHANGES_REQUESTED', 'PUBLISHED', 'HIDDEN'] as const) expect(canWithdraw(status)).toBe(true);
    for (const status of ['WITHDRAWN', 'DELETED', 'REJECTED'] as const) expect(canWithdraw(status)).toBe(false);
  });

  it('offers an appeal for a rejection before the deadline, once', () => {
    const now = Date.parse('2026-10-30T00:00:00Z');
    expect(canAppealRejection('REJECTED', '2026-11-17T17:59:59Z', null, now)).toBe(true);
    expect(canAppealRejection('REJECTED', '2026-10-29T17:59:59Z', null, now)).toBe(false); // deadline passed
    expect(canAppealRejection('REJECTED', '2026-11-17T17:59:59Z', 'received', now)).toBe(false); // already appealed
    expect(canAppealRejection('REJECTED', null, null, now)).toBe(false);
    expect(canAppealRejection('PENDING', '2026-11-17T17:59:59Z', null, now)).toBe(false);
    expect(canAppealRejection('REJECTED', 'not a date', null, now)).toBe(false);
  });
});

describe('appeal statement length (API.md 5.6)', () => {
  it('needs 20 to 2000 characters after trimming', () => {
    expect(appealStatementProblem('x'.repeat(APPEAL_MIN - 1))).toBe('too_short');
    expect(appealStatementProblem(`   ${'x'.repeat(APPEAL_MIN - 1)}   `)).toBe('too_short');
    expect(appealStatementProblem('x'.repeat(APPEAL_MIN))).toBeNull();
    expect(appealStatementProblem('x'.repeat(APPEAL_MAX))).toBeNull();
    expect(appealStatementProblem('x'.repeat(APPEAL_MAX + 1))).toBe('too_long');
  });

  it('counts Bangla by code point, like the server', () => {
    expect(appealStatementProblem('আমার অভিজ্ঞতা সত্য'.repeat(2))).toBeNull();
    expect(appealStatementProblem('আমি')).toBe('too_short');
  });
});

describe('diffEdit sends only what changed (API.md 5.5)', () => {
  const original = valuesFromDetail(detail());

  it('starts from the review as the server holds it', () => {
    expect(original.visitMonth).toBe('2026-09');
    expect(original.categoryRatings).toEqual({ FOOD: 4, SAFETY_PERCEPTION: 5 });
  });

  it('sends nothing when nothing changed', () => {
    expect(diffEdit(original, { ...original })).toEqual({});
    expect(hasChanges(diffEdit(original, { ...original }))).toBe(false);
  });

  it('sends one changed field and no unchanged ones', () => {
    expect(diffEdit(original, { ...original, title: 'Sunrise over the clouds' })).toEqual({ title: 'Sunrise over the clouds' });
    expect(diffEdit(original, { ...original, overallRating: 5 })).toEqual({ overall_rating: 5 });
  });

  it('turns the month input back into the first day of the month', () => {
    expect(diffEdit(original, { ...original, visitMonth: '2026-08' })).toEqual({ visit_month: '2026-08-01' });
  });

  it('ignores whitespace-only differences and normalises the text', () => {
    expect(diffEdit(original, { ...original, title: `  ${original.title}  ` })).toEqual({});
    expect(diffEdit(original, { ...original, body: `${original.body}\n` })).toEqual({});
    // NFC: a decomposed Bangla letter equals the composed one, so it is not a change
    const composed = valuesFromDetail(detail({ title: 'কিছু' }));
    expect(diffEdit(composed, { ...composed, title: 'কিছু'.normalize('NFD') })).toEqual({});
  });

  it('sends the whole category set when it changed, and {} when cleared', () => {
    expect(diffEdit(original, { ...original, categoryRatings: { FOOD: 3 } })).toEqual({ category_ratings: { FOOD: 3 } });
    expect(diffEdit(original, { ...original, categoryRatings: {} })).toEqual({ category_ratings: {} });
  });

  it('does not resend an unchanged set, even in a different key order', () => {
    expect(diffEdit(original, { ...original, categoryRatings: { SAFETY_PERCEPTION: 5, FOOD: 4 } })).toEqual({});
  });

  it('drops out-of-range category scores instead of sending them', () => {
    const changed = diffEdit(original, { ...original, categoryRatings: { FOOD: 9, VALUE: 2 } });
    expect(changed.category_ratings).toEqual({ VALUE: 2 });
  });

  it('never sends null or undefined values', () => {
    const changes = diffEdit(original, { ...original, title: 'New title', overallRating: 2 });
    for (const value of Object.values(changes)) expect(value).not.toBeNull();
    expect(JSON.stringify(changes)).not.toContain('null');
  });
});

const review = (id: string, rating: number, extra: Partial<PublicReview> = {}): PublicReview => ({
  id,
  author_type: 'GUEST',
  guest_tag: null,
  status: 'PUBLISHED',
  overall_rating: rating,
  published_at: '2026-10-01T00:00:00Z',
  title: id,
  body: 'text',
  ...extra,
});

describe('public review filters (R09)', () => {
  const items = [
    review('a', 5, { author_type: 'MEMBER' }),
    review('b', 3, { media: [{ id: 'm', kind: 'image', content_type: 'image/webp', url: 'u', alt_text: 'x', caption: null, width: 1, height: 1, duration_ms: null }] }),
    review('c', 5),
    review('d', 1, { author_type: 'MEMBER' }),
  ];
  const f = (over: Partial<ReviewFilters>): ReviewFilters => ({ ...DEFAULT_FILTERS, ...over });

  it('returns everything, in feed order, by default', () => {
    expect(applyReviewFilters(items, DEFAULT_FILTERS).map((r) => r.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(filtersActive(DEFAULT_FILTERS)).toBe(false);
  });

  it('filters by exact star rating', () => {
    expect(applyReviewFilters(items, f({ rating: 5 })).map((r) => r.id)).toEqual(['a', 'c']);
    expect(applyReviewFilters(items, f({ rating: 2 }))).toEqual([]);
  });

  it('filters by photos and by author type', () => {
    expect(applyReviewFilters(items, f({ withMedia: true })).map((r) => r.id)).toEqual(['b']);
    expect(applyReviewFilters(items, f({ author: 'member' })).map((r) => r.id)).toEqual(['a', 'd']);
    expect(applyReviewFilters(items, f({ author: 'guest' })).map((r) => r.id)).toEqual(['b', 'c']);
  });

  it('combines filters', () => {
    expect(applyReviewFilters(items, f({ rating: 5, author: 'member' })).map((r) => r.id)).toEqual(['a']);
  });

  it('sorts without changing ties or the input', () => {
    const before = items.map((r) => r.id);
    expect(applyReviewFilters(items, f({ sort: 'highest' })).map((r) => r.id)).toEqual(['a', 'c', 'b', 'd']);
    expect(applyReviewFilters(items, f({ sort: 'lowest' })).map((r) => r.id)).toEqual(['d', 'b', 'a', 'c']);
    expect(items.map((r) => r.id)).toEqual(before);
    expect(filtersActive(f({ sort: 'lowest' }))).toBe(true);
  });
});
