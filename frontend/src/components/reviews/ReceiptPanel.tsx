import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Copy, Download, KeyRound } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { STATUS_LABEL } from './reviewLabels';
import type { SubmittedReview } from './GuestReviewForm';

/**
 * Shows the receipt once after the server acknowledges the review (PF 13.5 step 2).
 * The receipt is held only in memory; nothing here writes it to storage.
 */
export const ReceiptPanel: React.FC<{ review: SubmittedReview; onDone: () => void }> = ({ review, onDone }) => {
  const { t } = useLanguage();
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Move focus to the result so keyboard and screen-reader users land on the receipt.
  useEffect(() => {
    headingRef.current?.focus();
    headingRef.current?.scrollIntoView({ block: 'center' });
  }, []);

  const receiptText = [
    'Abhijatri review receipt',
    `Review ID: ${review.review_id}`,
    `Receipt: ${review.receipt}`,
    '',
    'Keep this private. It lets you check the status of your review and withdraw it.',
    'It cannot be recovered if lost.',
  ].join('\n');

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(receiptText);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob([receiptText], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `abhijatri-review-${review.review_id.slice(0, 8)}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section aria-labelledby="receipt-heading" className="tonal-card p-6 flex flex-col gap-4 border-emerald-300 dark:border-emerald-800">
      <div className="flex items-center gap-3 text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 size={24} aria-hidden="true" />
        <h2 id="receipt-heading" ref={headingRef} tabIndex={-1} className="font-bold text-lg font-title">
          {review.duplicate_recovered
            ? t('এই রিভিউটি আগেই জমা হয়েছিল', 'This review was already submitted')
            : t('রিভিউ জমা হয়েছে', 'Review submitted')}
          {' — '}
          {t(...STATUS_LABEL[review.status])}
        </h2>
      </div>
      <p className="text-sm font-body text-on-surface dark:text-on-dark">
        {t(
          'নিচের রিসিপ্টটি এখনই সংরক্ষণ করুন। এটি আর দেখানো হবে না এবং হারালে পুনরুদ্ধার করা যাবে না।',
          'Save the receipt below now. It will not be shown again and cannot be recovered if lost.',
        )}
      </p>
      {Boolean(review.mediaUploaded) && (
        <p className="text-sm text-emerald-800 dark:text-emerald-300">
          {t(
            `${review.mediaUploaded}টি ছবি/ভিডিও আপলোড হয়েছে; মডারেটর অনুমোদনের পর দেখা যাবে।`,
            `${review.mediaUploaded} photo(s)/video uploaded; they appear after a moderator approves them.`,
          )}
        </p>
      )}
      {review.mediaFailed && review.mediaFailed.length > 0 && (
        <div role="alert" className="p-3 rounded-xl bg-error-container text-sm text-red-900 dark:bg-red-950/40 dark:text-red-200">
          <p className="font-semibold">{t('এগুলো যোগ করা যায়নি:', 'These could not be added:')}</p>
          <ul className="list-disc pl-5">
            {review.mediaFailed.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="p-4 rounded-xl bg-white dark:bg-dark-surface-2 border border-emerald-200 dark:border-emerald-800 font-mono text-xs text-on-surface dark:text-on-dark flex flex-col gap-2 break-all">
        <div>
          <dt className="font-sans font-bold text-on-surface-variant dark:text-on-dark-muted">{t('রিভিউ আইডি', 'Review ID')}</dt>
          <dd className="select-all">{review.review_id}</dd>
        </div>
        <div>
          <dt className="font-sans font-bold text-on-surface-variant dark:text-on-dark-muted inline-flex items-center gap-1">
            <KeyRound size={12} aria-hidden="true" />
            {t('রিসিপ্ট', 'Receipt')}
          </dt>
          <dd className="select-all">{review.receipt}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={copy} className="inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title">
          <Copy size={14} aria-hidden="true" />
          {copied ? t('কপি হয়েছে', 'Copied') : t('কপি করুন', 'Copy')}
        </button>
        <button type="button" onClick={download} className="inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title">
          <Download size={14} aria-hidden="true" />
          {t('ফাইল হিসেবে সংরক্ষণ', 'Save as file')}
        </button>
      </div>

      <label className="flex items-start gap-2 min-h-[44px] cursor-pointer text-sm text-on-surface dark:text-on-dark">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="mt-0.5 h-5 w-5 accent-forest-primary dark:accent-neon-lime" />
        <span>{t('আমি রিসিপ্টটি নিরাপদে সংরক্ষণ করেছি।', 'I have saved the receipt somewhere safe.')}</span>
      </label>
      <button
        type="button"
        onClick={onDone}
        disabled={!saved}
        className="self-start min-h-[44px] px-5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold font-title disabled:opacity-50"
      >
        {t('সম্পন্ন', 'Done')}
      </button>
    </section>
  );
};
