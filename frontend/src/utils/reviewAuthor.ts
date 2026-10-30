/**
 * Pure rules for the author controls (Gantt R09, Review.md 5.1 and 5.2, API.md 5.5 and 5.6).
 * They only decide what the interface offers; the server re-checks every one of them.
 */

import { cleanCategoryRatings } from '../api/reviews';
import type {
  CategoryRatings,
  ComfortTier,
  PublicReview,
  ReviewDetail,
  ReviewEditChanges,
  ReviewLanguage,
  ReviewStatus,
  TravellerType,
} from '../types';

/** A review can be edited only before it is published: PENDING or CHANGES_REQUESTED. */
export const canEdit = (status: ReviewStatus): boolean => status === 'PENDING' || status === 'CHANGES_REQUESTED';

/** Withdraw is offered until the review is already gone (the server treats a repeat as a success). */
export const canWithdraw = (status: ReviewStatus): boolean => !['WITHDRAWN', 'DELETED', 'REJECTED'].includes(status);

/** A guest may appeal a rejection only, and only before the deadline and while no appeal is filed. */
export function canAppealRejection(
  status: ReviewStatus,
  appealDeadline: string | null,
  appealState: string | null | undefined,
  now: number = Date.now(),
): boolean {
  if (status !== 'REJECTED' || !appealDeadline || appealState) return false;
  const deadline = Date.parse(appealDeadline);
  return Number.isFinite(deadline) && deadline > now;
}

export const APPEAL_MIN = 20;
export const APPEAL_MAX = 2000;

/** Code-point length of the trimmed text, which is how the server counts. */
export const codePoints = (value: string): number => [...value.trim()].length;

export function appealStatementProblem(statement: string): 'too_short' | 'too_long' | null {
  const length = codePoints(statement);
  if (length < APPEAL_MIN) return 'too_short';
  if (length > APPEAL_MAX) return 'too_long';
  return null;
}

/** What the edit form holds. `visitMonth` is `YYYY-MM`, the input's own format. */
export interface EditableValues {
  title: string;
  body: string;
  overallRating: number;
  visitMonth: string;
  language: ReviewLanguage;
  travellerType: TravellerType;
  comfortTier: ComfortTier;
  categoryRatings: CategoryRatings;
}

export function valuesFromDetail(detail: ReviewDetail): EditableValues {
  return {
    title: detail.title,
    body: detail.body,
    overallRating: detail.overall_rating,
    visitMonth: detail.visit_month.slice(0, 7),
    language: detail.language,
    travellerType: detail.traveller_type,
    comfortTier: detail.comfort_tier,
    categoryRatings: { ...detail.category_ratings },
  };
}

const sameCategories = (a: CategoryRatings, b: CategoryRatings): boolean => {
  const x = cleanCategoryRatings(a);
  const y = cleanCategoryRatings(b);
  const keys = new Set([...Object.keys(x), ...Object.keys(y)]);
  for (const key of keys) if (x[key as keyof CategoryRatings] !== y[key as keyof CategoryRatings]) return false;
  return true;
};

/**
 * Only the fields that changed are sent (API.md 5.5). `null` is never sent. `category_ratings` is sent
 * as a whole set only when it changed, and `{}` clears it. Text is trimmed and NFC-normalised first.
 */
export function diffEdit(original: EditableValues, current: EditableValues): ReviewEditChanges {
  const clean = (value: string) => value.trim().normalize('NFC');
  const changes: ReviewEditChanges = {};
  if (clean(current.title) !== clean(original.title)) changes.title = clean(current.title);
  if (clean(current.body) !== clean(original.body)) changes.body = clean(current.body);
  if (current.overallRating !== original.overallRating) changes.overall_rating = current.overallRating;
  if (current.visitMonth !== original.visitMonth) changes.visit_month = `${current.visitMonth}-01`;
  if (current.language !== original.language) changes.language = current.language;
  if (current.travellerType !== original.travellerType) changes.traveller_type = current.travellerType;
  if (current.comfortTier !== original.comfortTier) changes.comfort_tier = current.comfortTier;
  if (!sameCategories(original.categoryRatings, current.categoryRatings)) changes.category_ratings = cleanCategoryRatings(current.categoryRatings);
  return changes;
}

export const hasChanges = (changes: ReviewEditChanges): boolean => Object.keys(changes).length > 0;

// ---------------------------------------------------------------------------
// Public review list filters (R09). The feed has no server-side filter yet, so these apply to the
// reviews already loaded; the interface says so. Nothing is re-ordered on the server.
// ---------------------------------------------------------------------------

export type ReviewSort = 'newest' | 'highest' | 'lowest';

export interface ReviewFilters {
  /** 0 means all ratings. */
  rating: 0 | 1 | 2 | 3 | 4 | 5;
  withMedia: boolean;
  author: 'all' | 'member' | 'guest';
  sort: ReviewSort;
}

export const DEFAULT_FILTERS: ReviewFilters = { rating: 0, withMedia: false, author: 'all', sort: 'newest' };

export const filtersActive = (filters: ReviewFilters): boolean =>
  filters.rating !== 0 || filters.withMedia || filters.author !== 'all' || filters.sort !== 'newest';

/** Returns a new array; the input is never changed. Ties keep the feed's order (newest first). */
export function applyReviewFilters(items: readonly PublicReview[], filters: ReviewFilters): PublicReview[] {
  const kept = items.filter((review) => {
    if (filters.rating !== 0 && review.overall_rating !== filters.rating) return false;
    if (filters.withMedia && !(review.media && review.media.length > 0)) return false;
    if (filters.author === 'member' && review.author_type !== 'MEMBER') return false;
    if (filters.author === 'guest' && review.author_type !== 'GUEST') return false;
    return true;
  });
  const indexed = kept.map((review, index) => ({ review, index }));
  if (filters.sort === 'highest') indexed.sort((a, b) => b.review.overall_rating - a.review.overall_rating || a.index - b.index);
  if (filters.sort === 'lowest') indexed.sort((a, b) => a.review.overall_rating - b.review.overall_rating || a.index - b.index);
  return indexed.map(({ review }) => review);
}
