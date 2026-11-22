import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, Compass, LogOut, MessageSquarePlus, NotebookPen, PartyPopper, Star, UserRound } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { GUEST_NAME_MAX, normalizeGuestName } from '../api/guests';
import { getReviewParameters } from '../api/reviewParameters';
import { REVIEW_CATEGORIES } from '../api/reviews';
import { useApiResource } from '../hooks/useApiResource';
import { CATEGORY_LABEL } from '../components/reviews/reviewLabels';
import { formatNumber } from '../utils/format';
import { LoadingState, SlowNetworkHint } from '../components/common/StatusViews';
import { buttonVariants } from '@/components/ui/button';
import { useGuardedSignOut } from '../components/reviews/useGuardedSignOut';

/**
 * Guest entry (Review.md 3.2 step 1): the guest gives a name, which stays on this device for 30 days
 * after the last visit, and is welcomed by it with the browser's guest tag such as `1C669-J0TDY`
 * (Guest-Identity-and-Visits 3.3). Then the page shows what a review asks for, read from
 * `GET /review-parameters` (API.md 5.15).
 *
 * This is an entry point, never a gate: every app route still opens directly for guests.
 */
// shadcn Button variants. Text may contain a person's name of any length; Button wraps it.
const primaryButton = buttonVariants({ size: 'lg' });
const outlineButton = buttonVariants({ variant: 'outline', size: 'lg' });
const textButton = buttonVariants({ variant: 'link', size: 'sm', className: 'px-0 text-muted-foreground hover:text-primary text-xs' });

export const GuestEntryPage: React.FC = () => {
  const { t } = useLanguage();
  const { session, status, setGuestName, clearGuestName, startAsNewGuest, signOut } = useSession();
  // A member with unsent review drafts is asked first whether to keep them (guideline 6.7).
  const guardedSignOut = useGuardedSignOut();
  const navigate = useNavigate();
  const storedName = session.kind === 'guest' ? session.displayName : null;
  const guestTag = session.kind === 'guest' ? session.guestTag : null;

  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [renewing, setRenewing] = useState(false);
  const [leaving, setLeaving] = useState(false);

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
      <code className="px-1.5 py-0.5 rounded-sm bg-surface-container dark:bg-dark-surface-2 font-mono tracking-wide">{guestTag}</code>
    </p>
  );

  // Until the server says who this is, show neither the guest form nor the member choice.
  if (status === 'loading') return <LoadingState />;

  // A signed-in member cannot be a guest at the same time: the server keeps treating this browser
  // as the member while the session cookie exists. Offer the two honest choices instead of a guest
  // form that could never take effect.
  if (session.kind === 'member') {
    const leaveAccount = async () => {
      setLeaving(true);
      try {
        await guardedSignOut.request(); // the page then re-renders as a guest and shows the name form
      } finally {
        setLeaving(false);
      }
    };
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-4 lg:py-[clamp(0.5rem,2vh,1.5rem)] flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">
            {t('অতিথি হিসেবে প্রবেশ', 'Continue as a guest')}
          </h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted wrap-anywhere">
            {t(
              `আপনি ${session.displayName} হিসেবে সাইন ইন করা আছেন। অতিথি হতে হলে আগে সাইন আউট করতে হবে; সাইন আউটের পর আপনার রিভিউ ও অ্যাকাউন্ট আগের মতোই থাকবে।`,
              `You are signed in as ${session.displayName}. To use guest mode, sign out first; your account and reviews stay as they are.`,
            )}
          </p>
        </div>
        <div className="tonal-card p-6 flex flex-col gap-3">
          <Link
            to="/overview"
            className={primaryButton}
          >
            {t(`${session.displayName} হিসেবে চালিয়ে যান`, `Continue as ${session.displayName}`)}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <button
            type="button"
            onClick={() => void leaveAccount()}
            disabled={leaving}
            aria-busy={leaving}
            className={outlineButton}
          >
            <LogOut size={16} aria-hidden="true" />
            {leaving ? t('সাইন আউট হচ্ছে…', 'Signing out…') : t('সাইন আউট করে অতিথি হিসেবে চালিয়ে যান', 'Sign out and continue as a guest')}
          </button>
          <SlowNetworkHint active={leaving} />
        </div>
        {guardedSignOut.dialog}
      </div>
    );
  }

  if (!storedName) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-4 lg:py-[clamp(0.5rem,2vh,1.5rem)] flex flex-col gap-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">
            {t('অতিথি হিসেবে প্রবেশ', 'Continue as a guest')}
          </h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted wrap-anywhere">
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
              className="w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark aria-invalid:border-error-alert"
            />
            {error && (
              <p id="guest-name-error" className="text-xs text-error-alert dark:text-red-400">
                {error}
              </p>
            )}
          </div>
          <button
            type="submit"
            className={primaryButton}
          >
            {t('প্রবেশ করুন', 'Continue')}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 lg:py-[clamp(0.5rem,2vh,1.5rem)] flex flex-col gap-6">
      <section className="tonal-card p-6 sm:p-8 flex flex-col gap-3 bg-surface-sage/60 dark:bg-dark-surface-1" aria-live="polite">
        <PartyPopper size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark wrap-anywhere">
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
            to="/reviews/write"
            className={primaryButton}
          >
            <MessageSquarePlus size={16} aria-hidden="true" />
            {t('রিভিউ লিখুন', 'Write a review')}
          </Link>
          <Link
            to="/overview"
            className={outlineButton}
          >
            <Compass size={16} aria-hidden="true" />
            {t('গন্তব্য দেখুন', 'Explore destinations')}
          </Link>
        </div>
        <div className="flex flex-wrap gap-x-5">
          <button
            type="button"
            onClick={clearGuestName}
            className={textButton}
          >
            {t(`${storedName} নন? নাম পরিবর্তন করুন`, `Not ${storedName}? Change name`)}
          </button>
          <button
            type="button"
            onClick={() => {
              void signOut();
              navigate('/');
            }}
            className={textButton}
          >
            {t('বের হোন', 'Exit')}
          </button>
          <button
            type="button"
            onClick={handleNewGuest}
            disabled={renewing}
            className={textButton}
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
  const noteMin = parameters?.note.min_length ?? 1;

  return (
    <section aria-labelledby="review-guide-heading" className="tonal-card p-6 flex flex-col gap-4">
      <h2 id="review-guide-heading" className="text-lg font-bold font-title text-on-surface dark:text-on-dark">
        {t('রিভিউতে যা থাকবে', 'What a review includes')}
      </h2>
      <ul className="flex flex-col gap-3 text-sm">
        <li className="flex gap-3">
          <Star size={18} className="shrink-0 mt-0.5 fill-foreground text-foreground" aria-hidden="true" />
          <span>
            <strong>{t('সার্বিক রেটিং', 'Overall rating')}</strong>
            {': '}
            {t('আলাদা করে দিতে হয় না; নিচের সাতটি বিষয়ের রেটিং থেকে হিসাব করা হয়।', 'not asked separately; it is calculated from the seven category ratings below.')}
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
          {t('বিষয়ভিত্তিক রেটিং (সবগুলো আবশ্যক, ১–৫)', 'Ratings by category (all required, 1–5)')}
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
