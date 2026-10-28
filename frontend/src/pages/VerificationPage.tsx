import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BadgeCheck, FileUp, ShieldQuestion } from 'lucide-react';
import { EVIDENCE_MAX_BYTES, EVIDENCE_TYPES, getMyVerification, requestVerification, respondToVerification, uploadEvidence, withdrawVerification } from '../api/account';
import { Notice, accountErrorMessage, linkClass, primaryButtonClass } from '../components/auth/AccountUi';
import { LoadingState } from '../components/common/StatusViews';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { VerificationCaseView } from '../types';

const STATE_TEXT: Record<VerificationCaseView['state'], [string, string]> = {
  submitted: ['জমা হয়েছে, পর্যালোচনার অপেক্ষায়', 'Submitted, waiting for review'],
  in_review: ['পর্যালোচনা চলছে', 'Under review'],
  needs_clarification: ['মডারেটর আরও তথ্য চান', 'A moderator needs more information'],
  escalated: ['ঊর্ধ্বতন পর্যালোচনায়', 'With a senior reviewer'],
  approved: ['অনুমোদিত', 'Approved'],
  rejected: ['অনুমোদিত হয়নি', 'Not approved'],
  withdrawn: ['প্রত্যাহার করা হয়েছে', 'Withdrawn'],
};

/** Request the Verified Member badge (Moderation spec 6.2): a statement, a private evidence file, staff review. */
export const VerificationPage: React.FC = () => {
  const { t } = useLanguage();
  const { session, refresh, status } = useSession();
  const [data, setData] = useState<{ verified_member: boolean; case: VerificationCaseView | null } | null>(null);
  const [statement, setStatement] = useState('');
  const [answer, setAnswer] = useState('');
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await getMyVerification());
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
      await refresh();
    } catch (error) {
      setMessage({ tone: 'error', text: error instanceof Error && !('code' in error) ? error.message : accountErrorMessage(error, t) });
    } finally {
      setBusy(false);
    }
  };

  if (status === 'loading') return <LoadingState />; // still reading the session

  if (session.kind !== 'member') {
    return (
      <div className="max-w-xl mx-auto px-4 py-10">
        <Notice tone="info">
          {t('যাচাইয়ের জন্য আগে সাইন ইন করুন।', 'Sign in first to request verification.')}{' '}
          <Link to="/login" className={linkClass}>{t('সাইন ইন', 'Sign in')}</Link>
        </Notice>
      </div>
    );
  }

  const current = data?.case;
  const open = current && ['submitted', 'in_review', 'needs_clarification', 'escalated'].includes(current.state);
  const canUpload = current && ['submitted', 'in_review', 'needs_clarification'].includes(current.state) && current.evidence.length < 3;

  const onFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !current) return;
    if (!EVIDENCE_TYPES.includes(file.type)) return setMessage({ tone: 'error', text: t('শুধু JPG, PNG বা PDF।', 'Only JPG, PNG or PDF.') });
    if (file.size > EVIDENCE_MAX_BYTES) return setMessage({ tone: 'error', text: t('ফাইল ৫ MB-এর বেশি।', 'The file is larger than 5 MB.') });
    void run(() => uploadEvidence(current.id, file), t('ফাইল আপলোড হয়েছে।', 'File uploaded.'));
  };

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
      <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('যাচাইকৃত সদস্য', 'Verified Member')}</h1>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}

      {data?.verified_member && (
        <div className="tonal-card p-5 flex items-center gap-3">
          <BadgeCheck size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <div>
            <p className="font-bold text-on-surface dark:text-on-dark">{t('আপনি যাচাইকৃত সদস্য', 'You are a Verified Member')}</p>
            <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{t('আপনার রিভিউ কমিউনিটি রেটিংয়ে গণনা হয়।', 'Your reviews count towards the Community Rating.')}</p>
          </div>
        </div>
      )}

      {current && (
        <section className="tonal-card p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <ShieldQuestion size={18} aria-hidden="true" />
            <span className="font-bold text-on-surface dark:text-on-dark">{t(...STATE_TEXT[current.state])}</span>
          </div>
          {current.statement && <p className="text-sm text-on-surface-variant dark:text-on-dark-muted whitespace-pre-line">{current.statement}</p>}
          {current.state === 'needs_clarification' && current.decision_note && (
            <Notice tone="info">
              <strong>{t('মডারেটরের প্রশ্ন:', 'Question from the moderator:')}</strong> {current.decision_note}
            </Notice>
          )}
          {current.state === 'rejected' && (
            <p className="text-sm">
              {t('৩০ দিনের মধ্যে আপিল করতে পারবেন।', 'You can appeal within 30 days.')}{' '}
              <Link to="/account/appeals" className={linkClass}>{t('আপিল', 'Appeal')}</Link>
            </p>
          )}
          <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
            {t('প্রমাণ ফাইল', 'Evidence files')}: {current.evidence.filter((e) => e.status === 'uploaded').length}
            {' · '}
            {t('ফাইলগুলো গোপন থাকে এবং সিদ্ধান্তের পর মুছে ফেলা হয়।', 'Files are private and are deleted after the decision.')}
          </p>
          {canUpload && (
            <label className={`${primaryButtonClass} px-5 self-start cursor-pointer`}>
              <FileUp size={16} aria-hidden="true" />
              {t('ফাইল যোগ করুন (JPG, PNG, PDF, ৫ MB)', 'Add a file (JPG, PNG, PDF, 5 MB)')}
              <input type="file" accept={EVIDENCE_TYPES.join(',')} className="sr-only" onChange={onFile} disabled={busy} />
            </label>
          )}
          {current.state === 'needs_clarification' && (
            <div className="flex flex-col gap-2">
              <label htmlFor="verify-answer" className="text-xs font-bold">{t('আপনার উত্তর', 'Your answer')}</label>
              <textarea id="verify-answer" rows={3} maxLength={1000} value={answer} onChange={(e) => setAnswer(e.target.value)} className="rounded-xl p-3 bg-surface-sage/40 dark:bg-dark-surface-2" />
              <button type="button" disabled={busy || answer.trim().length < 3} className={`${primaryButtonClass} px-5 self-start`} onClick={() => void run(() => respondToVerification(current.id, answer.trim()), t('উত্তর পাঠানো হয়েছে।', 'Answer sent.'))}>
                {t('উত্তর পাঠান', 'Send answer')}
              </button>
            </div>
          )}
          {open && (
            <button type="button" disabled={busy} className={`${linkClass} text-xs self-start`} onClick={() => void run(() => withdrawVerification(current.id), t('প্রত্যাহার করা হয়েছে।', 'Withdrawn.'))}>
              {t('আবেদন প্রত্যাহার করুন', 'Withdraw the request')}
            </button>
          )}
        </section>
      )}

      {data && !data.verified_member && !open && (
        <section className="tonal-card p-5 flex flex-col gap-3">
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t('একজন মডারেটর আপনার তথ্য দেখে অনুমোদন দেবেন। জাতীয় পরিচয়পত্র নম্বর দেবেন না।', 'A moderator reviews your request by hand. Do not send a national ID number.')}
          </p>
          <label htmlFor="verify-statement" className="text-xs font-bold">{t('নিজের সম্পর্কে লিখুন', 'Tell us about yourself')}</label>
          <textarea id="verify-statement" rows={3} maxLength={1000} value={statement} onChange={(e) => setStatement(e.target.value)} className="rounded-xl p-3 bg-surface-sage/40 dark:bg-dark-surface-2" />
          <button type="button" disabled={busy} className={`${primaryButtonClass} px-5 self-start`} onClick={() => void run(() => requestVerification(statement.trim()), t('আবেদন জমা হয়েছে। এখন একটি প্রমাণ ফাইল যোগ করুন।', 'Request submitted. Now add an evidence file.'))}>
            {t('যাচাইয়ের আবেদন করুন', 'Request verification')}
          </button>
        </section>
      )}
    </div>
  );
};
