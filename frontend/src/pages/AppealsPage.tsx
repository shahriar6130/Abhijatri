import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Scale } from 'lucide-react';
import { getMyAppeals, submitAppeal, withdrawAppeal } from '../api/account';
import { Notice, accountErrorMessage, linkClass, primaryButtonClass } from '../components/auth/AccountUi';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { AppealView, AppealableDecision } from '../types';
import { formatTimestamp } from '../utils/format';

const STATE_TEXT: Record<AppealView['state'], [string, string]> = {
  received: ['গৃহীত', 'Received'],
  in_review: ['পর্যালোচনা চলছে', 'Under review'],
  upheld: ['মূল সিদ্ধান্ত বহাল', 'Original decision stands'],
  overturned: ['মূল সিদ্ধান্ত বাতিল', 'Original decision reversed'],
  withdrawn: ['প্রত্যাহার', 'Withdrawn'],
};

/** Appeal a decision on your own content or account within 30 days (Moderation spec 6.5). */
export const AppealsPage: React.FC = () => {
  const { t, language } = useLanguage();
  const { session } = useSession();
  const [data, setData] = useState<{ appeals: AppealView[]; appealable: AppealableDecision[] } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getMyAppeals());
    } catch (error) {
      setMessage({ tone: 'error', text: accountErrorMessage(error, t) });
    }
  }, [t]);

  useEffect(() => {
    if (session.kind === 'member') void load();
  }, [session.kind, load]);

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await work();
      setMessage({ tone: 'success', text: done });
      await load();
    } catch (error) {
      setMessage({ tone: 'error', text: accountErrorMessage(error, t) });
    } finally {
      setBusy(false);
    }
  };

  if (session.kind !== 'member') {
    return (
      <div className="max-w-xl mx-auto px-4 py-10">
        <Notice tone="info">
          {t('আপিল করতে সাইন ইন করুন।', 'Sign in to appeal a decision.')} <Link to="/login" className={linkClass}>{t('সাইন ইন', 'Sign in')}</Link>
        </Notice>
      </div>
    );
  }

  const openDecisions = data?.appealable.filter((d) => d.open) ?? [];

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
      <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('আপিল', 'Appeals')}</h1>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-bold font-title">{t('আপিলযোগ্য সিদ্ধান্ত', 'Decisions you can appeal')}</h2>
        {data && openDecisions.length === 0 && <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{t('এখন কোনো আপিলযোগ্য সিদ্ধান্ত নেই।', 'Nothing to appeal right now.')}</p>}
        {openDecisions.map((decision) => (
          <div key={decision.target_id} className="tonal-card p-4 flex flex-col gap-2">
            <p className="text-sm font-bold">{decision.label}</p>
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
              {t('শেষ সময়', 'Deadline')}: {formatTimestamp(decision.deadline_at, language)}
            </p>
            <label htmlFor={`reason-${decision.target_id}`} className="text-xs font-bold">{t('কেন সিদ্ধান্তটি ভুল (কমপক্ষে ১০ অক্ষর)', 'Why the decision is wrong (at least 10 characters)')}</label>
            <textarea
              id={`reason-${decision.target_id}`}
              rows={3}
              maxLength={1000}
              value={drafts[decision.target_id] ?? ''}
              onChange={(e) => setDrafts({ ...drafts, [decision.target_id]: e.target.value })}
              className="rounded-xl p-3 bg-surface-sage/40 dark:bg-dark-surface-2"
            />
            <button
              type="button"
              disabled={busy || (drafts[decision.target_id] ?? '').trim().length < 10}
              className={`${primaryButtonClass} px-5 self-start`}
              onClick={() => void run(() => submitAppeal(decision.target_type, decision.target_id, (drafts[decision.target_id] ?? '').trim()), t('আপিল জমা হয়েছে।', 'Appeal submitted.'))}
            >
              <Scale size={16} aria-hidden="true" />
              {t('আপিল করুন', 'Appeal')}
            </button>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-bold font-title">{t('আমার আপিল', 'My appeals')}</h2>
        {data?.appeals.length === 0 && <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{t('কোনো আপিল নেই।', 'No appeals.')}</p>}
        {data?.appeals.map((appeal) => (
          <div key={appeal.id} className="tonal-card p-4 flex flex-col gap-1 text-sm">
            <p className="font-bold">
              #{appeal.reference} · {t(...STATE_TEXT[appeal.state])}
            </p>
            <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">{appeal.reason}</p>
            {appeal.decision_note && <p className="text-xs">{t('সিদ্ধান্তের কারণ', 'Reason for the decision')}: {appeal.decision_note}</p>}
            {(appeal.state === 'received' || appeal.state === 'in_review') && (
              <button type="button" disabled={busy} className={`${linkClass} text-xs self-start`} onClick={() => void run(() => withdrawAppeal(appeal.id), t('প্রত্যাহার করা হয়েছে।', 'Withdrawn.'))}>
                {t('প্রত্যাহার করুন', 'Withdraw')}
              </button>
            )}
          </div>
        ))}
      </section>
    </div>
  );
};
