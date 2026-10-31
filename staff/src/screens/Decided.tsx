import { useCallback, useEffect, useState } from 'react';
import { getDecidedReviews, reopenReview } from '../api';
import { REOPEN_REASONS, errorText, isSuperadmin, reasonsFor, recoveryLeft } from '../logic';
import { useReasonCatalogue } from '../reasons';
import type { DecidedReview, Lang, Role } from '../types';
import { Notice, makeT } from '../ui';

type Status = 'REJECTED' | 'HIDDEN';

/**
 * Rejected and Hidden reviews (Moderation spec P-03). A rejected review can be sent back to the queue by a superadmin
 * for 30 days after the rejection; after that retention removes its text. A hidden review has no deadline: it is
 * restored from the report or the enforcement case that hid it.
 */
export function Decided({ lang, role }: { lang: Lang; role: Role }) {
  const t = makeT(lang);
  const catalogue = useReasonCatalogue();
  const [status, setStatus] = useState<Status>('REJECTED');
  const [items, setItems] = useState<DecidedReview[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(
    async (after?: string | null) => {
      try {
        const answer = await getDecidedReviews(status, after);
        setItems((current) => (after && current ? [...current, ...answer.items] : answer.items));
        setNext(answer.next_cursor);
        setError(null);
      } catch (failure) {
        setError(errorText(failure, lang));
      }
    },
    [status, lang],
  );

  useEffect(() => {
    setItems(null);
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const reopen = async (review: DecidedReview, reasonCode: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await reopenReview(review.review_id, { expectedVersion: review.version, reasonCode });
      setMessage(t('রিভিউটি আবার কিউতে গেছে।', 'The review is back in the queue.'));
      await load();
    } catch (failure) {
      setError(errorText(failure, lang));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>{t('বাতিল ও লুকানো রিভিউ', 'Rejected and hidden reviews')}</h2>
      <div className="row" role="tablist">
        {(['REJECTED', 'HIDDEN'] as Status[]).map((value) => (
          <button key={value} type="button" role="tab" aria-selected={status === value} className={status === value ? 'primary' : 'ghost'} onClick={() => setStatus(value)}>
            {value === 'REJECTED' ? t('বাতিল', 'Rejected') : t('লুকানো', 'Hidden')}
          </button>
        ))}
      </div>
      {status === 'REJECTED' && <p className="small muted">{t('বাতিলের ৩০ দিনের মধ্যে সুপারঅ্যাডমিন রিভিউ আবার কিউতে পাঠাতে পারেন। তার পরে লেখা মুছে ফেলা হয়।', 'Within 30 days of the rejection a superadmin can send a review back to the queue. After that its text is removed.')}</p>}
      {error && <Notice tone="error">{error}</Notice>}
      {message && <Notice tone="success">{message}</Notice>}
      {items?.length === 0 && <p className="muted">{t('কিছু নেই।', 'Nothing here.')}</p>}
      <ul className="list">
        {items?.map((review) => (
          <DecidedRow key={review.review_id} lang={lang} review={review} now={now} busy={busy} canReopen={isSuperadmin(role)} reasons={reasonsFor(catalogue, 'reopen', REOPEN_REASONS)} onReopen={reopen} />
        ))}
      </ul>
      {next && (
        <button type="button" className="ghost" onClick={() => void load(next)}>
          {t('আরও', 'More')}
        </button>
      )}
    </section>
  );
}

function DecidedRow({
  lang,
  review,
  now,
  busy,
  canReopen,
  reasons,
  onReopen,
}: {
  lang: Lang;
  review: DecidedReview;
  now: number;
  busy: boolean;
  canReopen: boolean;
  reasons: { code: string; bn: string; en: string }[];
  onReopen: (review: DecidedReview, reasonCode: string) => void;
}) {
  const t = makeT(lang);
  const left = recoveryLeft(review.recoverable_until, now);
  const [reason, setReason] = useState(reasons[0]?.code ?? '');
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="card">
      <div className="row small muted">
        <span className="tag">{review.status}</span>
        <span>{review.author === 'member' ? t('সদস্য', 'Member') : t('অতিথি', 'Guest')}</span>
        <span>{new Date(review.decided_at).toLocaleDateString(lang === 'bn' ? 'bn-BD' : 'en-GB')}</span>
        {review.reason_code && <span>{review.reason_code}</span>}
      </div>
      <strong>{review.purged ? t('[লেখা মুছে ফেলা হয়েছে]', '[text removed]') : review.title}</strong>
      {review.status === 'REJECTED' && (
        <p className="small muted" data-testid="recovery">
          {review.purged
            ? t('লেখা মুছে ফেলা হয়েছে; আর খোলা যাবে না।', 'The text was removed; it can no longer be reopened.')
            : left
              ? t(`আর ${left.days} দিন ${left.hours} ঘণ্টা বাকি`, `${left.days} days ${left.hours} hours left to reopen`)
              : t('খোলার সময় শেষ।', 'The reopen window has closed.')}
        </p>
      )}
      {review.status === 'HIDDEN' && review.counted_rating !== null && <p className="small muted">{t('লুকানো অবস্থায়ও রেটিং গণনায় আছে।', 'Its rating still counts while it is hidden.')}</p>}
      {review.status === 'REJECTED' && canReopen && left && (
        <div className="row">
          {!confirm ? (
            <button type="button" className="ghost" onClick={() => setConfirm(true)}>
              {t('আবার খুলুন', 'Reopen')}
            </button>
          ) : (
            <>
              <label className="sr-only" htmlFor={`reopen-${review.review_id}`}>
                {t('কারণ', 'Reason')}
              </label>
              <select id={`reopen-${review.review_id}`} value={reason} onChange={(event) => setReason(event.target.value)}>
                {reasons.map((option) => (
                  <option key={option.code} value={option.code}>
                    {lang === 'bn' ? option.bn : option.en}
                  </option>
                ))}
              </select>
              <button type="button" className="primary" disabled={busy} onClick={() => onReopen(review, reason)}>
                {t('নিশ্চিত করুন', 'Confirm reopen')}
              </button>
              <button type="button" className="ghost" onClick={() => setConfirm(false)}>
                {t('বাতিল', 'Cancel')}
              </button>
            </>
          )}
        </div>
      )}
    </li>
  );
}
