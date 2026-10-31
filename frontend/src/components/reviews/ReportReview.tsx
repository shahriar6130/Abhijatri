import React, { useState } from 'react';
import { Flag } from 'lucide-react';
import {
  CONTACT_MAX,
  REPORT_DETAILS_MAX,
  REPORT_REASONS,
  contactProblem,
  reportFailure,
  reportReview,
  reportReviewAnonymously,
  type ReportFailure,
  type ReportReason,
} from '../../api/reports';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import { TURNSTILE_SITE_KEY, TurnstileWidget } from './TurnstileWidget';

/**
 * "Report this review" (Review.md 5.4, Gantt R11). A signed-in member reports with their account; a visitor reports
 * anonymously, with a challenge and an optional contact for a follow-up. A report never removes a review by itself:
 * a moderator decides. Either way the same short thanks is shown, so nothing about the review or earlier reports leaks.
 */
export const ReportReview: React.FC<{ reviewId: string }> = ({ reviewId }) => {
  const { t, language } = useLanguage();
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ReportReason>('spam');
  const [details, setDetails] = useState('');
  const [contact, setContact] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const [challengeKey, setChallengeKey] = useState(0);
  const [status, setStatus] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const member = session.kind === 'member';

  const failureText = (kind: ReportFailure): string => {
    switch (kind) {
      case 'duplicate':
        return t('এই রিভিউয়ের জন্য আপনার একটি রিপোর্ট ইতিমধ্যে খোলা আছে।', 'You already have an open report on this review.');
      case 'rate_limited':
        return t('অনেকগুলো রিপোর্ট পাঠানো হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।', 'Too many reports were sent. Try again in a while.');
      case 'restricted':
        return t('আপনার অ্যাকাউন্টে এখন রিপোর্ট পাঠানো বন্ধ আছে।', 'Your account cannot send reports right now.');
      case 'challenge':
        return t('নিরাপত্তা যাচাই ব্যর্থ হয়েছে। আবার চেষ্টা করুন।', 'The security check failed. Try again.');
      case 'not_allowed':
        return t('নিজের রিভিউ রিপোর্ট করা যায় না।', 'You cannot report your own review.');
      case 'invalid':
        return t('তথ্য সঠিক নয়। কারণ ও যোগাযোগ দেখুন।', 'Something is not valid. Check the reason and the contact.');
      case 'offline':
        return t('সার্ভারের সাথে সংযোগ করা যায়নি।', 'Could not reach the server.');
      default:
        return t('রিপোর্ট পাঠানো যায়নি।', 'The report could not be sent.');
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!member && contactProblem(contact, false)) {
      setStatus({ tone: 'error', text: failureText('invalid') });
      return;
    }
    if (!member && TURNSTILE_SITE_KEY && !token) {
      setStatus({ tone: 'error', text: failureText('challenge') });
      return;
    }
    setBusy(true);
    try {
      if (member) await reportReview(reviewId, reason, details.trim());
      else await reportReviewAnonymously({ reviewId, reasonCode: reason, details, contact, turnstileToken: token });
      setStatus({ tone: 'ok', text: t('রিপোর্ট জমা হয়েছে। ধন্যবাদ।', 'Report sent. Thank you.') });
      setOpen(false);
      setDetails('');
      setContact('');
    } catch (error) {
      setStatus({ tone: 'error', text: failureText(reportFailure(error)) });
    } finally {
      setBusy(false);
      setToken(null);
      setChallengeKey((key) => key + 1); // a Turnstile token works once
    }
  };

  return (
    <div className="flex flex-col gap-2 text-xs">
      {status && (
        <p role={status.tone === 'error' ? 'alert' : 'status'} className={status.tone === 'error' ? 'text-error-alert dark:text-red-400' : 'text-forest-primary dark:text-neon-lime'}>
          {status.text}
        </p>
      )}
      {!open ? (
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            setStatus(null);
          }}
          className="self-start inline-flex items-center gap-1.5 min-h-[36px] text-on-surface-variant dark:text-on-dark-muted hover:underline"
        >
          <Flag size={13} aria-hidden="true" />
          {t('রিপোর্ট করুন', 'Report')}
        </button>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-2 p-3 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2">
          <label htmlFor={`report-reason-${reviewId}`} className="font-bold">
            {t('কারণ', 'Reason')}
          </label>
          <select
            id={`report-reason-${reviewId}`}
            value={reason}
            onChange={(e) => setReason(e.target.value as ReportReason)}
            className="min-h-[40px] rounded-lg px-2 bg-white dark:bg-dark-surface-1"
          >
            {REPORT_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {language === 'bn' ? r.bn : r.en}
              </option>
            ))}
          </select>
          <label htmlFor={`report-details-${reviewId}`} className="font-bold">
            {t('বিস্তারিত (ঐচ্ছিক)', 'Details (optional)')}
          </label>
          <textarea
            id={`report-details-${reviewId}`}
            rows={2}
            maxLength={REPORT_DETAILS_MAX}
            value={details}
            onChange={(e) => setDetails(e.target.value)}
            className="rounded-lg p-2 bg-white dark:bg-dark-surface-1"
          />
          {!member && (
            <>
              <label htmlFor={`report-contact-${reviewId}`} className="font-bold">
                {t('যোগাযোগ (ঐচ্ছিক)', 'Contact (optional)')}
              </label>
              <input
                id={`report-contact-${reviewId}`}
                type="text"
                inputMode="email"
                maxLength={CONTACT_MAX}
                autoComplete="off"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                aria-describedby={`report-contact-hint-${reviewId}`}
                className="min-h-[40px] rounded-lg px-2 bg-white dark:bg-dark-surface-1"
              />
              <p id={`report-contact-hint-${reviewId}`} className="text-on-surface-variant dark:text-on-dark-muted">
                {t('ইমেইল বা ফোন। শুধু কর্মীরা দেখবেন, ফলো-আপের জন্য; ৩০ দিন পরে মুছে ফেলা হয়।', 'An email or phone number. Only staff see it, for a follow-up; it is erased 30 days after the report closes.')}
              </p>
              {TURNSTILE_SITE_KEY && <TurnstileWidget key={challengeKey} action="guest-report" onToken={setToken} />}
            </>
          )}
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className="min-h-[40px] px-4 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base font-bold disabled:opacity-50">
              {t('পাঠান', 'Send report')}
            </button>
            <button type="button" onClick={() => setOpen(false)} className="min-h-[40px] px-4 rounded-full border border-surface-muted dark:border-dark-surface-2">
              {t('বাতিল', 'Cancel')}
            </button>
          </div>
        </form>
      )}
    </div>
  );
};
