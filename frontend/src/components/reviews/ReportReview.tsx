import React, { useState } from 'react';
import { Flag } from 'lucide-react';
import { ApiError } from '../../api/client';
import { reportReview, type ReportReason } from '../../api/auth';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';

const REASONS: { value: ReportReason; bn: string; en: string }[] = [
  { value: 'spam', bn: 'স্প্যাম', en: 'Spam' },
  { value: 'offensive', bn: 'আপত্তিকর', en: 'Offensive' },
  { value: 'false_information', bn: 'ভুল তথ্য', en: 'False information' },
  { value: 'privacy', bn: 'গোপনীয়তা', en: 'Privacy' },
  { value: 'conflict_of_interest', bn: 'স্বার্থের দ্বন্দ্ব', en: 'Conflict of interest' },
  { value: 'other', bn: 'অন্যান্য', en: 'Other' },
];

/**
 * "Report this review" for signed-in members (Gantt R11). Guests are not offered it; the API also
 * refuses it without a session. A moderator sees the report in the staff queue.
 */
export const ReportReview: React.FC<{ reviewId: string }> = ({ reviewId }) => {
  const { t, language } = useLanguage();
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ReportReason>('spam');
  const [details, setDetails] = useState('');
  const [status, setStatus] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (session.kind !== 'member') return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await reportReview(reviewId, reason, details.trim());
      setStatus({ tone: 'ok', text: t('রিপোর্ট জমা হয়েছে। ধন্যবাদ।', 'Report sent. Thank you.') });
      setOpen(false);
    } catch (error) {
      const duplicate = error instanceof ApiError && error.code === 'DUPLICATE_OPEN_REPORT';
      setStatus({
        tone: 'error',
        text: duplicate
          ? t('এই রিভিউয়ের জন্য আপনার একটি রিপোর্ট ইতিমধ্যে খোলা আছে।', 'You already have an open report on this review.')
          : t('রিপোর্ট পাঠানো যায়নি।', 'The report could not be sent.'),
      });
    } finally {
      setBusy(false);
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
        <button type="button" onClick={() => { setOpen(true); setStatus(null); }} className="self-start inline-flex items-center gap-1.5 min-h-[36px] text-on-surface-variant dark:text-on-dark-muted hover:underline">
          <Flag size={13} aria-hidden="true" />
          {t('রিপোর্ট করুন', 'Report')}
        </button>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-2 p-3 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2">
          <label htmlFor={`report-reason-${reviewId}`} className="font-bold">{t('কারণ', 'Reason')}</label>
          <select id={`report-reason-${reviewId}`} value={reason} onChange={(e) => setReason(e.target.value as ReportReason)} className="min-h-[40px] rounded-lg px-2 bg-white dark:bg-dark-surface-1">
            {REASONS.map((r) => (
              <option key={r.value} value={r.value}>{language === 'bn' ? r.bn : r.en}</option>
            ))}
          </select>
          <label htmlFor={`report-details-${reviewId}`} className="font-bold">{t('বিস্তারিত (ঐচ্ছিক)', 'Details (optional)')}</label>
          <textarea id={`report-details-${reviewId}`} rows={2} maxLength={1000} value={details} onChange={(e) => setDetails(e.target.value)} className="rounded-lg p-2 bg-white dark:bg-dark-surface-1" />
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
