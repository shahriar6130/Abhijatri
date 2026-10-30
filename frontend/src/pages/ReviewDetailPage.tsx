import React, { useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ArrowLeft, FilePenLine, Undo2 } from 'lucide-react';
import { ApiError } from '../api/client';
import { getDestination } from '../api/destinations';
import { getReview, withdrawMemberReview } from '../api/reviews';
import { Notice, linkClass } from '../components/auth/AccountUi';
import { LoadingState, describeError } from '../components/common/StatusViews';
import { CATEGORY_LABEL, COMFORT_TIERS, REVIEW_LANGUAGES, TRAVELLER_TYPES } from '../components/reviews/reviewLabels';
import { StatusChip } from '../components/reviews/StatusChip';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { ReviewAppealState, ReviewCategory, ReviewDetail } from '../types';
import { formatCalendarDate, formatTimestamp, pick } from '../utils/format';
import { canEdit, canWithdraw } from '../utils/reviewAuthor';

const APPEAL_TEXT: Record<ReviewAppealState, [string, string]> = {
  received: ['আপিল গৃহীত', 'Appeal received'],
  in_review: ['আপিল পর্যালোচনায়', 'Appeal under review'],
  upheld: ['আপিল পর্যালোচনা হয়েছে; মূল সিদ্ধান্ত বহাল', 'Your appeal was reviewed and the decision stands'],
  overturned: ['আপিল গৃহীত হয়েছে; রিভিউ আবার কিউতে', 'Your appeal was accepted; the review is back in the queue'],
};

/** One review of the signed-in author, with its history and the controls that apply to its state. */
export const ReviewDetailPage: React.FC = () => {
  const { t, language } = useLanguage();
  const { session, status: sessionStatus } = useSession();
  const { id = '' } = useParams();
  const location = useLocation();
  const flash = (location.state as { saved?: string } | null)?.saved;
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [destinationName, setDestinationName] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const review = await getReview(id);
      setDetail(review);
      getDestination(review.destination_id)
        .then((d) => setDestinationName(pick(language, d.name_bn, d.name_en)))
        .catch(() => setDestinationName(''));
    } catch (err: unknown) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [id, language]);

  useEffect(() => {
    if (session.kind === 'member') void load();
  }, [session.kind, load]);

  const withdraw = async () => {
    if (!detail) return;
    setBusy(true);
    setMessage(null);
    try {
      await withdrawMemberReview(detail.id, detail.version);
      setMessage({ tone: 'success', text: t('রিভিউ প্রত্যাহার করা হয়েছে।', 'Review withdrawn.') });
      setConfirming(false);
      await load();
    } catch (err: unknown) {
      const conflict = err instanceof ApiError && err.code === 'REVIEW_VERSION_CONFLICT';
      setMessage({ tone: 'error', text: conflict ? t('রিভিউটি বদলে গেছে। সর্বশেষ সংস্করণ লোড হচ্ছে।', 'The review changed. Loading the latest version.') : describeError(err, t) });
      if (conflict) await load();
    } finally {
      setBusy(false);
    }
  };

  if (sessionStatus === 'loading') return <LoadingState />;
  if (session.kind !== 'member') {
    return (
      <div className="max-w-xl mx-auto px-4 py-10">
        <Notice tone="info">{t('রিভিউ দেখতে সাইন ইন করুন।', 'Sign in to see this review.')} <Link to="/login" className={linkClass}>{t('সাইন ইন', 'Sign in')}</Link></Notice>
      </div>
    );
  }
  if (loading) return <LoadingState />;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="max-w-xl mx-auto px-4 py-10 flex flex-col gap-3">
        <Notice tone="error">{t('এই রিভিউটি পাওয়া যায়নি।', 'This review was not found.')}</Notice>
        <Link to="/account/reviews" className={linkClass}>{t('আমার রিভিউয়ে ফিরুন', 'Back to my reviews')}</Link>
      </div>
    );
  }
  if (error !== null || !detail) {
    return (
      <div className="max-w-xl mx-auto px-4 py-10 flex flex-col gap-3">
        <Notice tone="error">{describeError(error, t)}</Notice>
        <button type="button" onClick={() => void load()} className="self-start min-h-[44px] px-4 rounded-full border text-xs font-bold">{t('আবার চেষ্টা করুন', 'Retry')}</button>
      </div>
    );
  }

  const label = <K extends string>(list: [K, [string, string]][], value: K) => {
    const found = list.find(([v]) => v === value);
    return found ? t(...found[1]) : value;
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
      <Link to="/account/reviews" className={`${linkClass} inline-flex items-center gap-1 text-sm`}><ArrowLeft size={14} aria-hidden="true" />{t('আমার রিভিউ', 'My reviews')}</Link>
      {flash && <Notice tone="success">{flash}</Notice>}
      {message && <Notice tone={message.tone}>{message.text}</Notice>}

      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <h1 className="text-2xl font-bold font-title">{detail.title}</h1>
          <StatusChip status={detail.status} />
        </div>
        <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
          {destinationName || detail.destination_id.slice(0, 8)} · <span className="font-en">{formatCalendarDate(detail.visit_month, language)}</span> · {t(`সংস্করণ ${detail.version}`, `Version ${detail.version}`)}
        </p>
      </header>

      {detail.status === 'CHANGES_REQUESTED' && (
        <Notice tone="info">
          {t('মডারেটর আপনার রিভিউ ফেরত পাঠিয়েছেন। সম্পাদনা করে আবার জমা দিন।', 'A moderator sent your review back. Edit it to send it again.')}
          {detail.decision_reason && <> {t('কারণ', 'Reason')}: <span className="font-en font-semibold">{detail.decision_reason}</span></>}
        </Notice>
      )}
      {detail.status === 'REJECTED' && (
        <Notice tone="error">
          {t('রিভিউটি প্রকাশ করা হয়নি।', 'This review was not published.')}
          {detail.decision_reason && <> {t('কারণ', 'Reason')}: <span className="font-en font-semibold">{detail.decision_reason}</span>.</>}
          {detail.appeal_deadline && <> {t('আপিলের শেষ সময়', 'Appeal deadline')}: {formatTimestamp(detail.appeal_deadline, language)}. <Link to="/account/appeals" className={linkClass}>{t('আপিল করুন', 'Appeal')}</Link></>}
        </Notice>
      )}
      {detail.appeal_state && <Notice tone="info">{t(...APPEAL_TEXT[detail.appeal_state])}</Notice>}

      <section className="tonal-card p-5 flex flex-col gap-3" aria-label={t('রিভিউর বিষয়বস্তু', 'Review content')}>
        <p className="text-sm font-semibold" aria-label={t(`${detail.overall_rating} তারকা`, `${detail.overall_rating} out of 5 stars`)}><span className="font-en">{'★'.repeat(detail.overall_rating)}{'☆'.repeat(5 - detail.overall_rating)}</span></p>
        <p className="whitespace-pre-line font-body text-sm leading-relaxed">{detail.body}</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-on-surface-variant dark:text-on-dark-muted">
          <dt className="font-bold">{t('ভ্রমণকারীর ধরন', 'Traveller type')}</dt><dd>{label(TRAVELLER_TYPES, detail.traveller_type)}</dd>
          <dt className="font-bold">{t('খরচের ধরন', 'Comfort tier')}</dt><dd>{label(COMFORT_TIERS, detail.comfort_tier)}</dd>
          <dt className="font-bold">{t('ভাষা', 'Language')}</dt><dd>{label(REVIEW_LANGUAGES, detail.language)}</dd>
        </dl>
        {Object.keys(detail.category_ratings).length > 0 && (
          <ul className="flex flex-wrap gap-2 text-xs">
            {(Object.entries(detail.category_ratings) as [ReviewCategory, number][]).map(([category, rating]) => (
              <li key={category} className="px-2.5 py-1 rounded-full bg-surface-sage dark:bg-dark-surface-2">{t(...CATEGORY_LABEL[category].name)}: <span className="font-en">{rating}/5</span></li>
            ))}
          </ul>
        )}
      </section>

      {detail.media.length > 0 && (
        <section className="flex flex-col gap-2" aria-label={t('ছবি ও ভিডিও', 'Photos and video')}>
          <h2 className="text-sm font-bold">{t('ছবি ও ভিডিও', 'Photos and video')}</h2>
          <ul className="flex flex-col gap-1 text-xs">
            {detail.media.map((m) => (<li key={m.id}>{m.kind === 'image' ? t('ছবি', 'Photo') : t('ভিডিও', 'Video')}: {m.alt_text} · <span className="font-en font-semibold">{m.state}</span></li>))}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-2" aria-label={t('সংস্করণের ইতিহাস', 'Version history')}>
        <h2 className="text-sm font-bold">{t('সংস্করণের ইতিহাস', 'Version history')}</h2>
        <ol className="flex flex-col gap-1 text-xs">
          {[...detail.revisions].reverse().map((rev) => (
            <li key={rev.sequence}>{t(`সংস্করণ ${rev.sequence}`, `Version ${rev.sequence}`)} · <span className="font-en font-semibold">{rev.status}</span> · {formatTimestamp(rev.created_at, language)}</li>
          ))}
        </ol>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        {canEdit(detail.status) && (
          <Link to={`/account/reviews/${detail.id}/edit`} className="min-h-[44px] inline-flex items-center gap-1.5 px-5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold">
            <FilePenLine size={16} aria-hidden="true" />{t('সম্পাদনা', 'Edit')}
          </Link>
        )}
        {canWithdraw(detail.status) &&
          (confirming ? (
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-xs">{t('প্রত্যাহার করলে রিভিউটি সরে যাবে। নিশ্চিত?', 'Withdrawing removes the review. Are you sure?')}</span>
              <button type="button" disabled={busy} onClick={() => void withdraw()} className="min-h-[44px] px-4 rounded-full bg-red-700 text-white text-xs font-bold disabled:opacity-60">{t('হ্যাঁ, প্রত্যাহার করুন', 'Yes, withdraw')}</button>
              <button type="button" onClick={() => setConfirming(false)} className="min-h-[44px] px-4 rounded-full border text-xs font-bold">{t('বাতিল', 'Cancel')}</button>
            </span>
          ) : (
            <button type="button" onClick={() => setConfirming(true)} className="min-h-[44px] inline-flex items-center gap-1.5 px-5 rounded-full border border-red-300 text-red-700 dark:text-red-300 text-sm font-bold">
              <Undo2 size={16} aria-hidden="true" />{t('প্রত্যাহার', 'Withdraw')}
            </button>
          ))}
        {detail.status === 'PUBLISHED' && <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">{t('প্রকাশিত রিভিউ সম্পাদনা করা যায় না; প্রত্যাহার করে নতুন রিভিউ লিখুন।', 'A published review cannot be edited. Withdraw it and write a new one.')}</span>}
      </div>
    </div>
  );
};
