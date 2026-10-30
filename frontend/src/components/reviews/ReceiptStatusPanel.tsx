import React, { useState } from 'react';
import { FilePenLine, Scale, Search, Undo2 } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { appealRejectedReview, editGuestReview, getReceiptStatus, isReceiptFormat, withdrawGuestReview } from '../../api/reviews';
import type { ReceiptStatus, ReviewAppealState, ReviewEditChanges } from '../../types';
import { currentDisplayMonth, formatTimestamp } from '../../utils/format';
import { APPEAL_MAX, APPEAL_MIN, appealStatementProblem, canAppealRejection, canEdit, codePoints, type EditableValues } from '../../utils/reviewAuthor';
import { describeError } from '../common/StatusViews';
import { ReviewEditForm } from './ReviewEditForm';
import { STATUS_LABEL } from './reviewLabels';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FINAL_STATES = new Set(['WITHDRAWN', 'DELETED']);

const APPEAL_STATE_TEXT: Record<ReviewAppealState, [string, string]> = {
  received: ['আপিল গৃহীত', 'Appeal received'],
  in_review: ['আপিল পর্যালোচনায়', 'Appeal being reviewed'],
  upheld: ['আপিল পর্যালোচনা হয়েছে; মূল সিদ্ধান্ত বহাল', 'Your appeal was reviewed and the decision stands.'],
  overturned: ['আপিল গৃহীত হয়েছে; রিভিউ আবার অপেক্ষায়', 'Your appeal was accepted. The review is waiting again.'],
};

/** A guest cannot read a review back, so the edit form starts empty and sends only what the guest touches. */
const BLANK: EditableValues = {
  title: '',
  body: '',
  overallRating: 0,
  visitMonth: currentDisplayMonth(),
  language: 'EN',
  travellerType: 'SOLO',
  comfortTier: 'STANDARD',
  categoryRatings: {},
};

/** Receipt-scoped status check and withdrawal (API.md 5.3, 5.4). Inputs are never persisted. */
export const ReceiptStatusPanel: React.FC = () => {
  const { language, t } = useLanguage();
  const [reviewId, setReviewId] = useState('');
  const [receipt, setReceipt] = useState('');
  const [status, setStatus] = useState<ReceiptStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [editing, setEditing] = useState(false);
  const [appealing, setAppealing] = useState(false);
  const [statement, setStatement] = useState('');
  const [notice, setNotice] = useState<string | null>(null);

  const inputClass =
    'w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm font-mono text-on-surface dark:text-on-dark';

  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setStatus(null);
    setConfirmWithdraw(false);
    setEditing(false);
    setAppealing(false);
    setNotice(null);
    if (!UUID_PATTERN.test(reviewId.trim()) || !isReceiptFormat(receipt)) {
      setError(t('রিভিউ আইডি বা রিসিপ্টের ফরম্যাট সঠিক নয়।', 'The review ID or receipt format is not valid.'));
      return;
    }
    setBusy(true);
    try {
      setStatus(await getReceiptStatus(reviewId.trim(), receipt.trim()));
    } catch (err: unknown) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async () => {
    if (!status) return;
    setBusy(true);
    setError(null);
    try {
      setStatus(await withdrawGuestReview(status.review_id, receipt.trim(), status.version));
      setConfirmWithdraw(false);
    } catch (err: unknown) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async (changes: ReviewEditChanges) => {
    if (!status) return;
    await editGuestReview(status.review_id, receipt.trim(), status.version, changes);
    setStatus(await getReceiptStatus(status.review_id, receipt.trim()));
    setEditing(false);
    setNotice(t('সংরক্ষিত হয়েছে। রিভিউটি আবার মডারেটরের অপেক্ষায়।', 'Saved. Your review is waiting for moderation again.'));
  };

  /** After a version conflict: read the review's current status again so the next save carries the right version. */
  const refreshStatus = async () => {
    if (!status) return;
    try {
      setStatus(await getReceiptStatus(status.review_id, receipt.trim()));
    } catch (err: unknown) {
      setError(describeError(err, t));
    }
  };

  const sendAppeal = async () => {
    if (!status) return;
    setBusy(true);
    setError(null);
    try {
      await appealRejectedReview(status.review_id, receipt.trim(), statement);
      setStatus(await getReceiptStatus(status.review_id, receipt.trim()));
      setAppealing(false);
      setStatement('');
      setNotice(t('আপিল পাঠানো হয়েছে। অন্য একজন মডারেটর এটি দেখবেন।', 'Appeal sent. A different moderator will review it.'));
    } catch (err: unknown) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const statementProblem = appealStatementProblem(statement);

  return (
    <section aria-labelledby="status-heading" className="tonal-card p-6 flex flex-col gap-4">
      <h2 id="status-heading" className="text-lg font-bold font-title text-on-surface dark:text-on-dark">
        {t('রিসিপ্ট দিয়ে অবস্থা দেখুন', 'Check a review with its receipt')}
      </h2>
      <form onSubmit={check} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="status-review-id" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
            {t('রিভিউ আইডি', 'Review ID')}
          </label>
          <input id="status-review-id" value={reviewId} onChange={(e) => setReviewId(e.target.value)} autoComplete="off" spellCheck={false} className={inputClass} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="status-receipt" className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
            {t('রিসিপ্ট', 'Receipt')}
          </label>
          <input
            id="status-receipt"
            type="password"
            value={receipt}
            onChange={(e) => setReceipt(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="abr1_…"
            className={inputClass}
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="self-start inline-flex items-center gap-2 min-h-[44px] px-5 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title disabled:opacity-60"
        >
          <Search size={14} aria-hidden="true" />
          {t('অবস্থা দেখুন', 'Check status')}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-error-alert dark:text-red-400">
          {error}
        </p>
      )}

      {status && (
        <div role="status" className="p-4 rounded-xl bg-surface-container/60 dark:bg-dark-surface-2 flex flex-col gap-2 text-sm">
          <p className="font-bold font-title text-on-surface dark:text-on-dark">{t(...STATUS_LABEL[status.status])}</p>
          {status.published_at && (
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
              {t('প্রকাশ', 'Published')}: {formatTimestamp(status.published_at, language)}
            </p>
          )}
          {status.decision_reason && (
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
              {t('কারণ', 'Reason')}: <span className="font-en">{status.decision_reason}</span>
            </p>
          )}
          {status.appeal_deadline && (
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
              {t('আপিলের শেষ সময়', 'Appeal deadline')}: {formatTimestamp(status.appeal_deadline, language)}
              {' '}<span className="text-[11px]">({t('দিন শেষ, বাংলাদেশ সময়', 'end of day, Bangladesh time')})</span>
            </p>
          )}
          {status.status === 'CHANGES_REQUESTED' && (
            <p className="text-xs text-amber-900 dark:text-amber-200">
              {t('মডারেটর রিভিউটি ফেরত পাঠিয়েছেন। সম্পাদনা করলে এটি আবার অপেক্ষায় যাবে।', 'A moderator sent the review back. Editing it sends it to moderation again.')}
            </p>
          )}
          {status.appeal_state && <p className="text-xs font-semibold">{t(...APPEAL_STATE_TEXT[status.appeal_state])}</p>}
          {notice && <p role="status" className="text-xs font-semibold text-emerald-800 dark:text-emerald-300">{notice}</p>}

          {canEdit(status.status) && !editing && (
            <button type="button" onClick={() => setEditing(true)} className="self-start inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold">
              <FilePenLine size={14} aria-hidden="true" />
              {t('রিভিউ সম্পাদনা', 'Edit review')}
            </button>
          )}
          {editing && (
            <ReviewEditForm
              mode="guest"
              original={BLANK}
              onSave={saveEdit}
              onCancel={() => setEditing(false)}
              onReload={() => void refreshStatus()}
            />
          )}

          {canAppealRejection(status.status, status.appeal_deadline, status.appeal_state) &&
            (appealing ? (
              <div className="flex flex-col gap-2">
                <label htmlFor="appeal-statement" className="text-xs font-bold">
                  {t(`আপনার বক্তব্য (${APPEAL_MIN} থেকে ${APPEAL_MAX} অক্ষর, সাধারণ লেখা)`, `Your statement (${APPEAL_MIN} to ${APPEAL_MAX} characters, plain text)`)}
                </label>
                <textarea id="appeal-statement" rows={4} value={statement} maxLength={APPEAL_MAX + 200} onChange={(e) => setStatement(e.target.value)} aria-invalid={Boolean(statement) && statementProblem !== null} aria-describedby="appeal-count" className={`${inputClass} font-body`} />
                <p id="appeal-count" className={`text-[11px] font-en ${statement && statementProblem ? 'text-error-alert' : 'text-on-surface-variant dark:text-on-dark-muted'}`}>
                  {codePoints(statement)} / {APPEAL_MAX} {statementProblem === 'too_short' && t(`(কমপক্ষে ${APPEAL_MIN})`, `(at least ${APPEAL_MIN})`)}
                  {statementProblem === 'too_long' && t('(অনেক বড়)', '(too long)')}
                </p>
                <p className="text-[11px] text-on-surface-variant dark:text-on-dark-muted">{t('ফোন নম্বর বা ব্যক্তিগত তথ্য লিখবেন না।', 'Do not include phone numbers or private details.')}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={busy || statementProblem !== null} onClick={() => void sendAppeal()} className="min-h-[44px] px-5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold disabled:opacity-50">
                    {t('আপিল পাঠান', 'Send appeal')}
                  </button>
                  <button type="button" onClick={() => setAppealing(false)} className="min-h-[44px] px-4 rounded-full border text-xs font-bold">{t('বাতিল', 'Cancel')}</button>
                </div>
              </div>
            ) : (
              <button type="button" onClick={() => setAppealing(true)} className="self-start inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full border text-xs font-bold">
                <Scale size={14} aria-hidden="true" />
                {t('এই সিদ্ধান্তের বিরুদ্ধে আপিল', 'Appeal this decision')}
              </button>
            ))}
          {status.status === 'REJECTED' && status.appeal_deadline && !status.appeal_state && !canAppealRejection(status.status, status.appeal_deadline, status.appeal_state) && (
            <p className="text-xs">{t('আপিলের সময় শেষ হয়ে গেছে।', 'The appeal period has ended.')}</p>
          )}

          {!FINAL_STATES.has(status.status) &&
            (confirmWithdraw ? (
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="text-xs text-on-surface dark:text-on-dark">
                  {t('প্রত্যাহার করলে রিভিউটি সঙ্গে সঙ্গে সরিয়ে নেওয়া হবে। নিশ্চিত?', 'Withdrawing removes the review immediately. Are you sure?')}
                </span>
                <button type="button" onClick={withdraw} disabled={busy} className="min-h-[44px] px-4 rounded-full bg-red-700 text-white text-xs font-bold disabled:opacity-60">
                  {t('হ্যাঁ, প্রত্যাহার করুন', 'Yes, withdraw')}
                </button>
                <button type="button" onClick={() => setConfirmWithdraw(false)} className="min-h-[44px] px-4 rounded-full border text-xs font-bold">
                  {t('বাতিল', 'Cancel')}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmWithdraw(true)}
                className="self-start inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full border border-red-300 text-red-700 dark:text-red-300 dark:border-red-900 text-xs font-bold"
              >
                <Undo2 size={14} aria-hidden="true" />
                {t('রিভিউ প্রত্যাহার করুন', 'Withdraw review')}
              </button>
            ))}
        </div>
      )}
    </section>
  );
};
