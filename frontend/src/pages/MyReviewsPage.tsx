import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { FilePenLine, Loader2, PenSquare, Undo2, WifiOff } from 'lucide-react';
import { ApiError, NETWORK_ERROR } from '../api/client';
import { listAllDestinations } from '../api/destinations';
import { getMyReviews, withdrawMemberReview } from '../api/reviews';
import { Notice, linkClass } from '../components/auth/AccountUi';
import { EmptyState, LoadingState, describeError } from '../components/common/StatusViews';
import { STATUS_LABEL } from '../components/reviews/reviewLabels';
import { StatusChip } from '../components/reviews/StatusChip';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { DestinationSummary, ReviewStatus, ReviewSummary } from '../types';
import { formatCalendarDate, formatTimestamp, pick } from '../utils/format';
import { canEdit, canWithdraw } from '../utils/reviewAuthor';

const PAGE_SIZE = 20;
const STATUSES = Object.keys(STATUS_LABEL) as ReviewStatus[];

/** The signed-in member's own reviews: filters, newest first, "Show more" paging (Review.md 9.3, Gantt R09). */
export const MyReviewsPage: React.FC = () => {
  const { t, language } = useLanguage();
  const { session, status: sessionStatus } = useSession();
  const [params, setParams] = useSearchParams();
  const statusFilter = (STATUSES.includes(params.get('status') as ReviewStatus) ? params.get('status') : '') as ReviewStatus | '';
  const destinationFilter = params.get('destination') ?? '';

  const [items, setItems] = useState<ReviewSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [moreError, setMoreError] = useState<unknown>(null);
  const [destinations, setDestinations] = useState<DestinationSummary[]>([]);
  const [announce, setAnnounce] = useState('');
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine);
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
    };
  }, []);

  useEffect(() => {
    if (session.kind !== 'member') return;
    const controller = new AbortController();
    listAllDestinations(controller.signal).then(setDestinations).catch(() => undefined);
    return () => controller.abort();
  }, [session.kind]);

  // A new filter starts again from the newest page: the old cursor belongs to the old listing.
  useEffect(() => {
    if (session.kind !== 'member') return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setCursor(null);
    getMyReviews({ status: statusFilter, destinationId: destinationFilter, limit: PAGE_SIZE })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setCursor(page.next_cursor);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session.kind, statusFilter, destinationFilter, attempt]);

  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await getMyReviews({ status: statusFilter, destinationId: destinationFilter, after: cursor, limit: PAGE_SIZE });
      const fresh = page.items.filter((item) => !items.some((have) => have.id === item.id));
      setItems((prev) => [...prev, ...fresh]);
      setCursor(page.next_cursor);
      setAnnounce(t(`আরও ${fresh.length}টি রিভিউ লোড হয়েছে।`, `${fresh.length} more reviews loaded.`));
    } catch (err: unknown) {
      if (err instanceof ApiError && err.code === 'INVALID_CURSOR') setAttempt((n) => n + 1); // start the list again
      else setMoreError(err);
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, statusFilter, destinationFilter, items, t]);

  const setFilter = (key: 'status' | 'destination', value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const withdraw = async (review: ReviewSummary) => {
    setBusyId(review.id);
    setMessage(null);
    try {
      const result = await withdrawMemberReview(review.id, review.version);
      setItems((prev) => prev.map((item) => (item.id === review.id ? { ...item, status: result.status, version: result.version } : item)));
      setMessage({ tone: 'success', text: t('রিভিউ প্রত্যাহার করা হয়েছে।', 'Review withdrawn.') });
      setConfirming(null);
    } catch (err: unknown) {
      const conflict = err instanceof ApiError && err.code === 'REVIEW_VERSION_CONFLICT';
      setMessage({ tone: 'error', text: conflict ? t('রিভিউটি বদলে গেছে। তালিকা রিলোড করা হচ্ছে।', 'The review changed. Reloading the list.') : describeError(err, t) });
      if (conflict) setAttempt((n) => n + 1);
    } finally {
      setBusyId(null);
    }
  };

  const destinationName = (id: string): string => {
    const found = destinations.find((d) => d.id === id);
    return found ? pick(language, found.name_bn, found.name_en) : id.slice(0, 8);
  };

  if (sessionStatus === 'loading') return <LoadingState />;
  if (session.kind !== 'member') {
    return (
      <div className="max-w-xl mx-auto px-4 py-10">
        <Notice tone="info">
          {t('আপনার রিভিউ দেখতে সাইন ইন করুন।', 'Sign in to see your reviews.')} <Link to="/login" className={linkClass}>{t('সাইন ইন', 'Sign in')}</Link>
        </Notice>
      </div>
    );
  }

  const offlineFailure = error instanceof ApiError && error.code === NETWORK_ERROR;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 ref={heading} className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('আমার রিভিউ', 'My reviews')}</h1>
        <Link to="/reviews" className="inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title">
          <PenSquare size={16} aria-hidden="true" />
          {t('নতুন রিভিউ লিখুন', 'Write a review')}
        </Link>
      </div>

      <form role="search" aria-label={t('রিভিউ ফিল্টার', 'Review filters')} className="flex flex-wrap gap-3" onSubmit={(e) => e.preventDefault()}>
        <div className="flex flex-col gap-1">
          <label htmlFor="my-status" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{t('অবস্থা', 'Status')}</label>
          <select id="my-status" value={statusFilter} onChange={(e) => setFilter('status', e.target.value)} className="min-h-[44px] px-3 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 text-sm">
            <option value="">{t('সব অবস্থা', 'All statuses')}</option>
            {STATUSES.map((s) => (<option key={s} value={s}>{t(...STATUS_LABEL[s])}</option>))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="my-destination" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{t('গন্তব্য', 'Destination')}</label>
          <select id="my-destination" value={destinationFilter} onChange={(e) => setFilter('destination', e.target.value)} className="min-h-[44px] px-3 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 text-sm">
            <option value="">{t('সব গন্তব্য', 'All destinations')}</option>
            {destinations.map((d) => (<option key={d.id} value={d.id}>{pick(language, d.name_bn, d.name_en)}</option>))}
          </select>
        </div>
        {(statusFilter || destinationFilter) && (
          <button type="button" onClick={() => setParams(new URLSearchParams(), { replace: true })} className="self-end min-h-[44px] px-4 text-xs font-bold underline">
            {t('ফিল্টার মুছুন', 'Clear filters')}
          </button>
        )}
      </form>

      {!online && (
        <Notice tone="info">
          <span className="inline-flex items-center gap-2"><WifiOff size={16} aria-hidden="true" />{t('আপনি অফলাইনে আছেন। অনলাইনে ফিরলে রিভিউ দেখা যাবে।', 'You are offline. Your reviews load when you reconnect.')}</span>
        </Notice>
      )}
      {message && <Notice tone={message.tone}>{message.text}</Notice>}

      {loading && <LoadingState label={t('রিভিউ লোড হচ্ছে…', 'Loading your reviews…')} />}
      {!loading && error !== null && (
        <div role="alert" className="p-4 rounded-xl border border-red-200 bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-200 text-sm flex flex-col gap-2">
          <p>{offlineFailure ? t('সার্ভারের সাথে সংযোগ করা যায়নি।', 'Could not reach the server.') : describeError(error, t)}</p>
          {error instanceof ApiError && error.requestId && <p className="text-[11px] font-mono">request_id: {error.requestId}</p>}
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className="self-start min-h-[44px] px-4 rounded-full border border-red-700 text-xs font-bold">{t('আবার চেষ্টা করুন', 'Retry')}</button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <EmptyState
          title={statusFilter || destinationFilter ? t('এই ফিল্টারে কোনো রিভিউ নেই', 'No reviews match these filters') : t('আপনি এখনও কোনো রিভিউ লেখেননি', 'You have not written a review yet')}
          action={<Link to="/destinations" className={linkClass}>{t('গন্তব্য দেখুন', 'Browse destinations')}</Link>}
        />
      )}

      {!loading && !error && items.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label={t('আপনার রিভিউ', 'Your reviews')}>
          {items.map((review) => (
            <li key={review.id} className="tonal-card p-4 flex flex-col gap-2" data-review-id={review.id}>
              <div className="flex flex-wrap items-center gap-2 justify-between">
                <p className="text-sm font-bold font-title">{destinationName(review.destination_id)} · <span className="font-en font-normal">{formatCalendarDate(review.visit_month, language)}</span></p>
                <StatusChip status={review.status} />
              </div>
              <p className="text-base font-semibold">{review.title}</p>
              <p className="text-xs text-on-surface-variant dark:text-on-dark-muted font-en" aria-label={t(`${review.overall_rating} তারকা`, `${review.overall_rating} out of 5`)}>{'★'.repeat(review.overall_rating)}{'☆'.repeat(5 - review.overall_rating)} · {formatTimestamp(review.created_at, language)}</p>
              {review.status === 'REJECTED' && review.appeal_deadline && (
                <p className="text-xs">{t('আপিলের শেষ সময়', 'Appeal deadline')}: {formatTimestamp(review.appeal_deadline, language)}</p>
              )}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <Link to={`/account/reviews/${review.id}`} className="min-h-[44px] inline-flex items-center px-4 rounded-full border text-xs font-bold">{t('দেখুন', 'View')}</Link>
                {canEdit(review.status) && (
                  <Link to={`/account/reviews/${review.id}/edit`} className="min-h-[44px] inline-flex items-center gap-1.5 px-4 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold">
                    <FilePenLine size={14} aria-hidden="true" />{t('সম্পাদনা', 'Edit')}
                  </Link>
                )}
                {review.status === 'REJECTED' && (
                  <Link to="/account/appeals" className="min-h-[44px] inline-flex items-center px-4 rounded-full border text-xs font-bold">{t('আপিল', 'Appeal')}</Link>
                )}
                {canWithdraw(review.status) &&
                  (confirming === review.id ? (
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-xs">{t('প্রত্যাহার করলে রিভিউটি সরে যাবে। নিশ্চিত?', 'Withdrawing removes the review. Are you sure?')}</span>
                      <button type="button" disabled={busyId === review.id} onClick={() => void withdraw(review)} className="min-h-[44px] px-4 rounded-full bg-red-700 text-white text-xs font-bold disabled:opacity-60">{t('হ্যাঁ, প্রত্যাহার করুন', 'Yes, withdraw')}</button>
                      <button type="button" onClick={() => setConfirming(null)} className="min-h-[44px] px-4 rounded-full border text-xs font-bold">{t('বাতিল', 'Cancel')}</button>
                    </span>
                  ) : (
                    <button type="button" onClick={() => setConfirming(review.id)} className="min-h-[44px] inline-flex items-center gap-1.5 px-4 rounded-full border border-red-300 text-red-700 dark:text-red-300 text-xs font-bold">
                      <Undo2 size={14} aria-hidden="true" />{t('প্রত্যাহার', 'Withdraw')}
                    </button>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      {moreError !== null && <p role="alert" className="text-xs text-error-alert dark:text-red-400">{describeError(moreError, t)}</p>}
      {!loading && !error && items.length > 0 && (cursor ? (
        <button type="button" onClick={() => void loadMore()} disabled={loadingMore} className="self-center inline-flex items-center gap-2 min-h-[44px] px-5 rounded-full border border-surface-muted dark:border-dark-surface-2 text-xs font-bold font-title text-forest-primary dark:text-neon-lime disabled:opacity-60">
          {loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
          {t('আরও রিভিউ দেখুন', 'Show more reviews')}
        </button>
      ) : (
        <p className="text-center text-xs text-on-surface-variant dark:text-on-dark-muted">{t('এটাই আপনার সব রিভিউ।', 'That is all your reviews.')}</p>
      ))}
      <div className="sr-only" role="status" aria-live="polite">{announce}</div>
    </div>
  );
};
