import React, { useState } from 'react';
import {
  CONTACT_MAX,
  REMOVAL_STATEMENT_MIN,
  REPORT_DETAILS_MAX,
  contactProblem,
  isReviewId,
  reportFailure,
  requestRemoval,
} from '../../api/reports';
import { useLanguage } from '../../context/LanguageContext';
import { TURNSTILE_SITE_KEY, TurnstileWidget } from './TurnstileWidget';

/**
 * "I lost my receipt" (Review.md 9.2). The author cannot prove ownership with a receipt, so a moderator checks it
 * through the contact given here. The review is not touched until that check, and the answer is the same whether or
 * not the id matches a review.
 */
export const RemovalRequestForm: React.FC = () => {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [reviewId, setReviewId] = useState('');
  const [statement, setStatement] = useState('');
  const [contact, setContact] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const [challengeKey, setChallengeKey] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!isReviewId(reviewId)) next.reviewId = t('রিভিউ আইডি একটি UUID হতে হবে।', 'The review ID must look like 3f2a1c0e-…');
    if (statement.trim().length < REMOVAL_STATEMENT_MIN) next.statement = t(`অন্তত ${REMOVAL_STATEMENT_MIN} অক্ষরে লিখুন।`, `Write at least ${REMOVAL_STATEMENT_MIN} characters.`);
    const problem = contactProblem(contact, true);
    if (problem) next.contact = problem === 'REQUIRED' ? t('যোগাযোগ দিন: ইমেইল বা ফোন।', 'Give a contact: an email or phone number.') : t('সঠিক ইমেইল বা ফোন নম্বর দিন।', 'Enter a valid email address or phone number.');
    if (TURNSTILE_SITE_KEY && !token) next.turnstile = t('নিরাপত্তা যাচাই সম্পূর্ণ করুন।', 'Complete the security check.');
    setErrors(next);
    setFormError(null);
    const first = ['reviewId', 'statement', 'contact'].find((key) => next[key]);
    if (first) {
      // Move focus to the first field to fix, as the other forms do, so keyboard and screen-reader users land on it.
      document.getElementById({ reviewId: 'removal-review-id', statement: 'removal-statement', contact: 'removal-contact' }[first])?.focus();
    }
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    try {
      await requestRemoval({ reviewId, statement, contact, turnstileToken: token });
      setSent(true);
      setOpen(false);
      setReviewId('');
      setStatement('');
      setContact('');
    } catch (error) {
      const kind = reportFailure(error);
      setFormError(
        kind === 'rate_limited'
          ? t('অনেকবার চেষ্টা হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।', 'Too many attempts. Try again in a while.')
          : kind === 'challenge'
            ? t('নিরাপত্তা যাচাই ব্যর্থ হয়েছে। আবার চেষ্টা করুন।', 'The security check failed. Try again.')
            : kind === 'offline'
              ? t('সার্ভারের সাথে সংযোগ করা যায়নি।', 'Could not reach the server.')
              : t('অনুরোধ পাঠানো যায়নি। তথ্য দেখে আবার চেষ্টা করুন।', 'The request could not be sent. Check the details and try again.'),
      );
    } finally {
      setBusy(false);
      setToken(null);
      setChallengeKey((key) => key + 1);
    }
  };

  const field = 'w-full min-h-[44px] rounded-xl px-3 bg-white dark:bg-dark-surface-1 border border-surface-muted/50 dark:border-dark-surface-2';
  const error = (key: string) =>
    errors[key] ? (
      <p id={`removal-${key}-error`} role="alert" className="text-xs text-error-alert dark:text-red-400">
        {errors[key]}
      </p>
    ) : null;

  return (
    <section className="tonal-card p-6 flex flex-col gap-3" aria-labelledby="removal-heading">
      <h2 id="removal-heading" className="text-lg font-bold font-title text-on-surface dark:text-on-dark">
        {t('রিসিপ্ট হারিয়ে গেছে?', 'Lost your receipt?')}
      </h2>
      <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
        {t('রিভিউ সরানোর অনুরোধ পাঠান। একজন মডারেটর আপনার যোগাযোগের মাধ্যমে যাচাই করবেন যে রিভিউটি আপনার।', 'Ask for your review to be removed. A moderator will check, through your contact, that it is yours.')}
      </p>
      {sent && (
        <p role="status" className="text-sm text-forest-primary dark:text-neon-lime font-bold">
          {t('অনুরোধ পাওয়া গেছে। যাচাই শেষ না হওয়া পর্যন্ত রিভিউটি যেমন আছে তেমনই থাকবে।', 'Request received. The review stays as it is until the check is done.')}
        </p>
      )}
      {!open ? (
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            setSent(false);
          }}
          className="self-start min-h-[44px] px-5 rounded-full border border-surface-muted dark:border-dark-surface-2 font-bold"
        >
          {t('অপসারণের অনুরোধ', 'Request removal')}
        </button>
      ) : (
        <form onSubmit={submit} noValidate className="flex flex-col gap-3">
          <label htmlFor="removal-review-id" className="text-sm font-bold">
            {t('রিভিউ আইডি', 'Review ID')}
          </label>
          <input id="removal-review-id" className={field} value={reviewId} onChange={(e) => setReviewId(e.target.value)} aria-invalid={Boolean(errors.reviewId)} aria-describedby={errors.reviewId ? 'removal-reviewId-error' : undefined} autoComplete="off" />
          {error('reviewId')}
          <label htmlFor="removal-statement" className="text-sm font-bold">
            {t('কেন এটি আপনার? (যেমন, কবে ও কোথায় লিখেছিলেন)', 'Why is it yours? (for example when and where you wrote it)')}
          </label>
          <textarea id="removal-statement" rows={3} maxLength={REPORT_DETAILS_MAX} className={field} value={statement} onChange={(e) => setStatement(e.target.value)} aria-invalid={Boolean(errors.statement)} aria-describedby={errors.statement ? 'removal-statement-error' : undefined} />
          {error('statement')}
          <label htmlFor="removal-contact" className="text-sm font-bold">
            {t('যোগাযোগ (ইমেইল বা ফোন)', 'Contact (email or phone)')}
          </label>
          <input id="removal-contact" className={field} maxLength={CONTACT_MAX} inputMode="email" autoComplete="off" value={contact} onChange={(e) => setContact(e.target.value)} aria-invalid={Boolean(errors.contact)} aria-describedby={errors.contact ? 'removal-contact-error' : undefined} />
          {error('contact')}
          <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">{t('শুধু কর্মীরা দেখবেন; কাজ শেষ হওয়ার ৩০ দিন পরে মুছে ফেলা হয়।', 'Only staff see it; it is erased 30 days after the request is closed.')}</p>
          {TURNSTILE_SITE_KEY && (
            <div>
              <TurnstileWidget key={challengeKey} action="guest-removal" onToken={setToken} />
              {error('turnstile')}
            </div>
          )}
          {formError && (
            <p role="alert" className="p-3 rounded-xl bg-error-container text-sm text-red-900 dark:bg-red-950/40 dark:text-red-200">
              {formError}
            </p>
          )}
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className="min-h-[44px] px-5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base font-bold disabled:opacity-50">
              {busy ? '…' : t('অনুরোধ পাঠান', 'Send request')}
            </button>
            <button type="button" onClick={() => setOpen(false)} className="min-h-[44px] px-5 rounded-full border border-surface-muted dark:border-dark-surface-2">
              {t('বাতিল', 'Cancel')}
            </button>
          </div>
        </form>
      )}
    </section>
  );
};
