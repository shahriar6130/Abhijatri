import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, MessageSquarePlus, Star } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { detectReviewLanguage, getReviewFeed } from '../../api/reviews';
import type { CategoryAverage, PublicReview } from '../../types';
import { formatNumber, formatTimestamp } from '../../utils/format';
import { DEFAULT_FILTERS, applyReviewFilters, filtersActive, type ReviewFilters } from '../../utils/reviewAuthor';
import { describeError, EmptyState, ErrorState, LoadingState } from '../common/StatusViews';
import { CategoryAverages, CategoryChips } from '../destination/CategoryAverages';
import { ReportReview } from './ReportReview';
import { ReviewMediaGallery } from './ReviewMediaGallery';

/**
 * The feed (API.md 5.8) does not return the review's declared language, so tag it by the script it
 * is written in. Mixed text inherits the page language. Replace with the API field once it exists.
 */
function reviewLang(review: PublicReview): 'bn' | 'en' | undefined {
  const detected = detectReviewLanguage(`${review.title} ${review.body}`);
  return detected === 'BN' ? 'bn' : detected === 'EN' ? 'en' : undefined;
}

const PAGE_SIZE = 10;

/** Published reviews for one destination, newest first, with cursor paging (API.md 5.8). */
export const ReviewFeedSection: React.FC<{ destinationId: string }> = ({ destinationId }) => {
  const { language, t } = useLanguage();
  const [items, setItems] = useState<PublicReview[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [guest, setGuest] = useState<{ average: number | null; count: number }>({ average: null, count: 0 });
  const [guestCategories, setGuestCategories] = useState<CategoryAverage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [moreError, setMoreError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [filters, setFilters] = useState<ReviewFilters>(DEFAULT_FILTERS);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getReviewFeed(destinationId, { limit: PAGE_SIZE, signal: controller.signal })
      .then((feed) => {
        setItems(feed.items);
        setCursor(feed.next_cursor);
        setGuest({ average: feed.guest_rating_average, count: feed.guest_rating_count });
        setGuestCategories(feed.guest_category_averages ?? []);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [destinationId, attempt]);

  const loadMore = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const feed = await getReviewFeed(destinationId, { after: cursor, limit: PAGE_SIZE });
      setItems((prev) => [...prev, ...feed.items.filter((item) => !prev.some((p) => p.id === item.id))]);
      setCursor(feed.next_cursor);
    } catch (err: unknown) {
      setMoreError(err);
    } finally {
      setLoadingMore(false);
    }
  };

  const shown = applyReviewFilters(items, filters);
  const active = filtersActive(filters);

  return (
    <section aria-labelledby="reviews-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="reviews-heading" className="text-xl font-bold font-title text-on-surface dark:text-on-dark">
            {t('ভ্রমণকারীদের রিভিউ', 'Traveller reviews')}
          </h2>
          {!loading && !error && (
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
              {guest.count > 0 && guest.average !== null
                ? t(
                    `অতিথি মতামত: ${formatNumber(guest.average, language, 1)} / ৫ (${formatNumber(guest.count, language)}টি রিভিউ)`,
                    `Guest Feedback: ${formatNumber(guest.average, language, 1)} / 5 from ${guest.count} review${guest.count === 1 ? '' : 's'}`,
                  )
                : t('মডারেশনের পর প্রকাশিত রিভিউ এখানে দেখা যাবে।', 'Reviews appear here after moderation.')}
            </p>
          )}
        </div>
        <Link
          to={`/reviews?destination=${destinationId}`}
          className="inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title"
        >
          <MessageSquarePlus size={16} aria-hidden="true" />
          {t('রিভিউ লিখুন', 'Write a review')}
        </Link>
      </div>

      {!loading && !error && (
        <CategoryAverages
          averages={guestCategories}
          title={t('অতিথি মতামত: বিষয়ভিত্তিক', 'Guest Feedback by category')}
        />
      )}

      {!loading && !error && items.length > 0 && (
        <form role="search" aria-label={t('রিভিউ ফিল্টার', 'Review filters')} className="flex flex-col gap-3 p-3 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2" onSubmit={(e) => e.preventDefault()}>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="feed-rating" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{t('রেটিং', 'Rating')}</label>
              <select id="feed-rating" value={filters.rating} onChange={(e) => setFilters({ ...filters, rating: Number(e.target.value) as ReviewFilters['rating'] })} className="min-h-[44px] px-3 rounded-xl bg-white dark:bg-dark-surface-1 text-sm">
                <option value={0}>{t('সব রেটিং', 'All ratings')}</option>
                {[5, 4, 3, 2, 1].map((n) => (<option key={n} value={n}>{t(`${n} তারকা`, `${n} star${n === 1 ? '' : 's'}`)}</option>))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="feed-author" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{t('লেখক', 'Author')}</label>
              <select id="feed-author" value={filters.author} onChange={(e) => setFilters({ ...filters, author: e.target.value as ReviewFilters['author'] })} className="min-h-[44px] px-3 rounded-xl bg-white dark:bg-dark-surface-1 text-sm">
                <option value="all">{t('সবাই', 'Everyone')}</option>
                <option value="member">{t('সদস্য', 'Members')}</option>
                <option value="guest">{t('অতিথি', 'Guests')}</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="feed-sort" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{t('সাজান', 'Sort by')}</label>
              <select id="feed-sort" value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value as ReviewFilters['sort'] })} className="min-h-[44px] px-3 rounded-xl bg-white dark:bg-dark-surface-1 text-sm">
                <option value="newest">{t('সবচেয়ে নতুন', 'Newest')}</option>
                <option value="highest">{t('সর্বোচ্চ রেটিং', 'Highest rating')}</option>
                <option value="lowest">{t('সর্বনিম্ন রেটিং', 'Lowest rating')}</option>
              </select>
            </div>
            <label className="inline-flex items-center gap-2 min-h-[44px] text-sm cursor-pointer">
              <input type="checkbox" checked={filters.withMedia} onChange={(e) => setFilters({ ...filters, withMedia: e.target.checked })} className="h-5 w-5 accent-forest-primary dark:accent-neon-lime" />
              {t('ছবি বা ভিডিওসহ', 'With photos or video')}
            </label>
            {active && (
              <button type="button" onClick={() => setFilters(DEFAULT_FILTERS)} className="min-h-[44px] px-3 text-xs font-bold underline">{t('ফিল্টার মুছুন', 'Clear filters')}</button>
            )}
          </div>
          <p className="text-[11px] text-on-surface-variant dark:text-on-dark-muted" role="status" aria-live="polite">
            {t(`লোড হওয়া ${formatNumber(items.length, language)}টির মধ্যে ${formatNumber(shown.length, language)}টি দেখাচ্ছে।`, `Showing ${shown.length} of the ${items.length} loaded reviews.`)}
            {cursor && ' ' + t('ফিল্টার শুধু লোড হওয়া রিভিউতে কাজ করে; আরও দেখতে "আরও রিভিউ" চাপুন।', 'Filters apply to loaded reviews; use "Show more reviews" to load more.')}
          </p>
        </form>
      )}

      {loading && <LoadingState label={t('রিভিউ লোড হচ্ছে…', 'Loading reviews…')} />}
      {!loading && error !== null && <ErrorState error={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {!loading && !error && items.length === 0 && (
        <EmptyState
          title={t('এখনো কোনো প্রকাশিত রিভিউ নেই', 'No published reviews yet')}
          hint={t('প্রথম রিভিউটি আপনিই লিখুন। মডারেশনের পর এটি প্রকাশিত হবে।', 'Be the first to write one. It is published after moderation.')}
        />
      )}

      {!loading && !error && items.length > 0 && shown.length === 0 && (
        <EmptyState title={t('এই ফিল্টারে কোনো রিভিউ মেলেনি', 'No loaded review matches these filters')} hint={cursor ? t('আরও রিভিউ লোড করুন বা ফিল্টার মুছুন।', 'Load more reviews or clear the filters.') : t('ফিল্টার মুছুন।', 'Clear the filters.')} />
      )}
      {!loading && !error && shown.length > 0 && (
        <ul className="flex flex-col gap-3">
          {shown.map((review) => (
            <li key={review.id} className="tonal-card p-5 flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-on-surface-variant dark:text-on-dark-muted">
                <span className="inline-flex items-center gap-0.5" aria-label={t(
                    `৫-এর মধ্যে ${formatNumber(review.overall_rating, language)} তারকা`,
                    `${review.overall_rating} out of 5 stars`,
                  )}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Star
                      key={n}
                      size={14}
                      aria-hidden="true"
                      className={n <= review.overall_rating ? 'fill-amber-400 text-amber-400' : 'text-surface-muted dark:text-dark-surface-2'}
                    />
                  ))}
                </span>
                {/* A guest's name is never shown: "Anonymous guest · TAG" (owner, 22 Oct 2026). */}
                <span className="font-semibold text-on-surface dark:text-on-dark">
                  {review.author_type === 'GUEST' ? t('বেনামী অতিথি', 'Anonymous guest') : review.author_display_name || t('সদস্য', 'Member')}
                  {review.author_type === 'GUEST' && review.guest_tag && (
                    <>
                      {' · '}
                      <code className="font-mono font-normal tracking-wide">{review.guest_tag}</code>
                    </>
                  )}
                </span>
                <span className="ml-auto">{formatTimestamp(review.published_at, language)}</span>
              </div>
              {/* Plain text only: React escapes it, and user HTML is never rendered (Review.md 10). */}
              {/* Each review keeps its own language, not the page's (UI-Architecture L6, U3). */}
              <h3 lang={reviewLang(review)} className="text-base font-bold font-title text-on-surface dark:text-on-dark">{review.title}</h3>
              <p lang={reviewLang(review)} className="text-sm font-body leading-relaxed text-on-surface dark:text-on-dark whitespace-pre-line">{review.body}</p>
              <ReviewMediaGallery media={review.media} />
              <CategoryChips ratings={review.category_ratings} />
              <ReportReview reviewId={review.id} />
            </li>
          ))}
        </ul>
      )}

      {moreError !== null && (
        <p role="alert" className="text-xs text-error-alert dark:text-red-400">
          {describeError(moreError, t)}
        </p>
      )}
      {cursor && !loading && !error && (
        <button
          type="button"
          onClick={loadMore}
          disabled={loadingMore}
          className="self-center inline-flex items-center gap-2 min-h-[44px] px-5 rounded-full border border-surface-muted dark:border-dark-surface-2 text-xs font-bold font-title text-forest-primary dark:text-neon-lime disabled:opacity-60"
        >
          {loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
          {t('আরও রিভিউ দেখুন', 'Show more reviews')}
        </button>
      )}
    </section>
  );
};
