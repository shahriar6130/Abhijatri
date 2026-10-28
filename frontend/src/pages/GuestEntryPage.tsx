import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Compass, MessageSquarePlus, NotebookPen, PartyPopper, Star, UserRound } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { GUEST_NAME_MAX, normalizeGuestName } from '../api/guests';
import { getReviewParameters } from '../api/reviewParameters';
import { REVIEW_CATEGORIES } from '../api/reviews';
import { useApiResource } from '../hooks/useApiResource';
import { CATEGORY_LABEL } from '../components/reviews/reviewLabels';
import { formatNumber } from '../utils/format';

/**
 * Guest entry (Review.md 3.2 step 1): the guest gives a name, which stays on this device for 30 days
 * after the last visit, and is welcomed by it with the browser's guest tag such as `1C669-J0TDY`
 * (Guest-Identity-and-Visits 3.3). Then the page shows what a review asks for, read from
 * `GET /review-parameters` (API.md 5.15).
 *
 * This is an entry point, never a gate: every app route still opens directly for guests.
 */
export const GuestEntryPage: React.FC = () => {
  const { t } = useLanguage();
  const { session, setGuestName, clearGuestName, startAsNewGuest, signOut } = useSession();
  const navigate = useNavigate();
  const storedName = session.kind === 'guest' ? session.displayName : null;
  const guestTag = session.kind === 'guest' ? session.guestTag : null;

  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [renewing, setRenewing] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!normalizeGuestName(name)) {
      setError(t('আপনার নাম লিখুন।', 'Please enter your name.'));
      return;
    }
    setError(null);
    setGuestName(name);
  };

  // Drafts live only in the review form's state (no stored draft yet, R15), so nothing unsent can
  // be orphaned by a new scope secret here.
  const handleNewGuest = async () => {
    setRenewing(true);
    try {
      await startAsNewGuest();
    } finally {
      setRenewing(false);
    }
  };

  const tagBadge = guestTag && (
    <p className="inline-flex items-center gap-2 text-sm font-semibold text-forest-primary dark:text-neon-lime">
      <UserRound size={16} aria-hidden="true" />
      {t('আপনি অতিথি', 'You are Guest')}{' '}
      <code className="px-1.5 py-0.5 rounded bg-surface-container dark:bg-dark-surface-2 font-mono tracking-wide">{guestTag}</code>
    </p>
  );

  if (!storedName) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">
            {t('অতিথি হিসেবে প্রবেশ', 'Continue as a guest')}
          </h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t(
              'কোনো অ্যাকাউন্ট লাগবে না। নামটি শুধু এই ডিভাইসে ৩০ দিন থাকে; সার্ভারে পাঠানো হয় না।',
              'No account needed. Your name stays on this device for 30 days and is never sent to the server.',
            )}
          </p>
          {tagBadge}
        </div>
        <form onSubmit={handleSubmit} noValidate className="tonal-card p-6 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="guest-name" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
              {t('আপনার নাম', 'Your name')}
            </label>
            <input
              id="guest-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={GUEST_NAME_MAX}
              autoComplete="nickname"
              autoFocus
              aria-invalid={Boolean(error)}
              aria-describedby={error ? 'guest-name-error' : undefined}
              className="w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark aria-[invalid=true]:border-error-alert"
            />
            {error && (
              <p id="guest-name-error" className="text-xs text-error-alert dark:text-red-400">
                {error}
              </p>
            )}
          </div>
          <button
            type="submit"
            className="inline-flex items-center justify-center gap-2 min-h-[48px] rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title disabled:opacity-60"
          >
            {t('প্রবেশ করুন', 'Continue')}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-14 flex flex-col gap-6">
      <section className="tonal-card p-6 sm:p-8 flex flex-col gap-3 bg-surface-sage/60 dark:bg-dark-surface-1" aria-live="polite">
        <PartyPopper size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark break-words">
          {t(`স্বাগতম, ${storedName}!`, `Welcome, ${storedName}!`)}
        </h1>
        {tagBadge}
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t(
            'এই ব্রাউজার থেকে আপনার সব রিভিউতে একই অতিথি ট্যাগ দেখাবে, তাই পাঠকরা বুঝবেন সেগুলো একই অতিথির।',
            'Your reviews from this browser show the same guest tag, so readers can see they came from the same guest.',
          )}
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <Link
            to="/reviews"
            className="inline-flex items-center gap-2 min-h-[48px] px-6 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title"
          >
            <MessageSquarePlus size={16} aria-hidden="true" />
            {t('রিভিউ লিখুন', 'Write a review')}
          </Link>
          <Link
            to="/overview"
            className="inline-flex items-center gap-2 min-h-[48px] px-6 rounded-full border border-forest-primary/40 dark:border-neon-lime/40 text-forest-primary dark:text-neon-lime text-sm font-bold font-title"
          >
            <Compass size={16} aria-hidden="true" />
            {t('গন্তব্য দেখুন', 'Explore destinations')}
          </Link>
        </div>
        <div className="flex flex-wrap gap-x-5">
          <button
            type="button"
            onClick={clearGuestName}
            className="min-h-[44px] text-xs font-semibold text-on-surface-variant dark:text-on-dark-muted underline underline-offset-2"
          >
            {t(`${storedName} নন? নাম পরিবর্তন করুন`, `Not ${storedName}? Change name`)}
          </button>
          <button
            type="button"
            onClick={() => {
              signOut();
              navigate('/');
            }}
            className="min-h-[44px] text-xs font-semibold text-on-surface-variant dark:text-on-dark-muted underline underline-offset-2"
          >
            {t('সাইন আউট', 'Sign out')}
          </button>
          <button
            type="button"
            onClick={handleNewGuest}
            disabled={renewing}
            className="min-h-[44px] text-xs font-semibold text-on-surface-variant dark:text-on-dark-muted underline underline-offset-2 disabled:opacity-60"
          >
            {t('নতুন অতিথি হিসেবে শুরু করুন', 'Start as a new guest')}
          </button>
        </div>
      </section>

      <ReviewGuide />
    </div>
  );
};

/** What a review asks for, from the server's parameters; falls back to the local labels. */
const ReviewGuide: React.FC = () => {
  const { language, t } = useLanguage();
  const { data: parameters } = useApiResource(() => getReviewParameters(), []);

  const categories = parameters
    ? parameters.categories.map((c) => ({ code: c.code, name: c.name[language], prompt: c.prompt[language] }))
    : REVIEW_CATEGORIES.map((code) => ({
        code,
        name: t(...CATEGORY_LABEL[code].name),
        prompt: t(...CATEGORY_LABEL[code].prompt),
      }));
  const noteMin = parameters?.note.min_length ?? 20;

  return (
    <section aria-labelledby="review-guide-heading" className="tonal-card p-6 flex flex-col gap-4">
      <h2 id="review-guide-heading" className="text-lg font-bold font-title text-on-surface dark:text-on-dark">
        {t('রিভিউতে যা থাকবে', 'What a review includes')}
      </h2>
      <ul className="flex flex-col gap-3 text-sm">
        <li className="flex gap-3">
          <Star size={18} className="shrink-0 mt-0.5 fill-amber-400 text-amber-400" aria-hidden="true" />
          <span>
            <strong>{t('সার্বিক রেটিং (আবশ্যক)', 'Overall rating (required)')}</strong>
            {': '}
            {t('১ থেকে ৫ তারকা।', '1 to 5 stars.')}
          </span>
        </li>
        <li className="flex gap-3">
          <NotebookPen size={18} className="shrink-0 mt-0.5 text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <span>
            <strong>{t('আপনার নোট (আবশ্যক)', 'Your note (required)')}</strong>
            {': '}
            {t(
              `কমপক্ষে ${formatNumber(noteMin, language)} অক্ষরে আপনার অভিজ্ঞতা লিখুন।`,
              `describe your experience in at least ${noteMin} characters.`,
            )}
          </span>
        </li>
      </ul>
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-bold text-on-surface dark:text-on-dark">
          {t('বিষয়ভিত্তিক রেটিং (ঐচ্ছিক, ১–৫)', 'Ratings by category (optional, 1–5)')}
        </h3>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {categories.map((category) => (
            <li key={category.code} className="p-3 rounded-xl bg-surface-container/60 dark:bg-dark-surface-2 flex flex-col">
              <span className="text-sm font-semibold text-on-surface dark:text-on-dark">{category.name}</span>
              <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">{category.prompt}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
        {t(
          'অতিথির রেটিং আলাদা "অতিথি মতামত"-এ গণনা হয়; কমিউনিটি রেটিং শুধু যাচাইকৃত সদস্যদের রিভিউ থেকে, অন্তত পাঁচটি হলে।',
          'Guest ratings count towards the separate Guest Feedback. The Community Rating uses only Verified Member reviews, from five reviews.',
        )}
      </p>
    </section>
  );
};
