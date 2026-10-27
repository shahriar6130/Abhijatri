import { useState } from 'react';
import { decideAppeal, enforcementAction, evidenceUrl, transitionVerification } from '../api';
import { enforcementActions, verificationMoves, type VerificationMove } from '../logic';
import type { AppealSubject, EnforcementSubject, Lang, QueueItem, Role, VerificationSubject } from '../types';
import { Notice, makeT } from '../ui';

type Run = (work: () => Promise<string | void>) => Promise<void>;
interface Lease {
  token: string;
  expiresAt: string;
}

const MOVE_TEXT: Record<VerificationMove, [string, string]> = {
  in_review: ['পর্যালোচনা শুরু', 'Start review'],
  needs_clarification: ['প্রশ্ন করুন', 'Ask a question'],
  approved: ['অনুমোদন', 'Approve'],
  rejected: ['প্রত্যাখ্যান', 'Reject'],
  escalated: ['উপরে পাঠান', 'Escalate'],
};

// ---------------- verification ----------------

export function VerificationBody({ subject, lang, canView, run }: { subject: VerificationSubject; lang: Lang; canView: boolean; run: Run }) {
  const t = makeT(lang);
  const open = (evidenceId: string) =>
    run(async () => {
      const link = await evidenceUrl(subject.case_id, evidenceId);
      window.open(link.url, '_blank', 'noopener,noreferrer');
      return t('৬০ সেকেন্ডের জন্য গোপন লিংক খোলা হয়েছে (অডিট লগে লেখা হলো)।', 'A private link opened for 60 seconds (recorded in the audit log).');
    });
  return (
    <div className="content-box">
      <div className="row small muted">
        <span className="tag">{subject.state}</span>
        <span>
          {subject.applicant?.display_name} · {subject.applicant?.email}
        </span>
      </div>
      {subject.statement && <p className="content-text">{subject.statement}</p>}
      <div className="row small">
        <strong>{t('প্রমাণ', 'Evidence')}:</strong>
        {subject.evidence.length === 0 && <span className="muted">{t('এখনো কোনো ফাইল নেই', 'no file yet')}</span>}
        {subject.evidence.map((item, index) => (
          <button key={item.id} type="button" className="ghost" disabled={!canView} onClick={() => void open(item.id)}>
            {t('ফাইল', 'File')} {index + 1} ({item.content_type.split('/')[1]})
          </button>
        ))}
      </div>
      {!canView && subject.evidence.length > 0 && <p className="muted small">{t('ফাইল দেখতে আগে কাজটি নিন।', 'Claim the task to view the files.')}</p>}
    </div>
  );
}

export function VerificationForm({ lang, role, item, subject, lease, busy, run }: { lang: Lang; role: Role; item: QueueItem; subject: VerificationSubject; lease: Lease; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const [note, setNote] = useState('');
  const moves = verificationMoves(subject.state, role);
  if (moves.length === 0) return <Notice tone="info">{t('এই অবস্থায় আপনার জন্য কোনো পদক্ষেপ নেই।', 'No action for your role in this state.')}</Notice>;
  const go = (to: VerificationMove) =>
    run(async () => {
      const result = await transitionVerification(subject.case_id, {
        to,
        expectedVersion: subject.version,
        reasonCode: to === 'approved' ? 'documents-ok' : to === 'rejected' ? 'not-eligible' : to === 'needs_clarification' ? 'question' : to,
        note,
        taskId: item.id,
        leaseToken: lease.token,
      });
      return t(`অবস্থা: ${result.state}`, `State: ${result.state}`);
    });
  return (
    <fieldset className="stack decision">
      <legend>{t('যাচাইয়ের সিদ্ধান্ত', 'Verification decision')}</legend>
      <label htmlFor="verify-note">{t('নোট (প্রশ্ন করলে আবশ্যক; আবেদনকারী দেখবেন)', 'Note (required for a question; the applicant sees it)')}</label>
      <textarea id="verify-note" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        {moves.map((to) => (
          <button key={to} type="button" className={to === 'approved' ? 'primary' : 'ghost'} disabled={busy || (to === 'needs_clarification' && note.trim().length < 3)} onClick={() => void go(to)}>
            {t(...MOVE_TEXT[to])}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

// ---------------- appeals ----------------

export function AppealBody({ subject, lang }: { subject: AppealSubject; lang: Lang }) {
  const t = makeT(lang);
  return (
    <div className="content-box">
      <div className="row small muted">
        <span className="tag">{subject.state}</span>
        <span>
          {subject.target_type} {subject.target_id.slice(0, 8)}
        </span>
        <span>
          {t('শেষ সময়', 'Deadline')}: {new Date(subject.deadline_at).toLocaleDateString()}
        </span>
      </div>
      <p className="content-text">{subject.reason}</p>
      {subject.original_decider_is_you && (
        <Notice tone="info">{t('মূল সিদ্ধান্তটি আপনার, তাই এই আপিল অন্য কেউ দেখবেন।', 'You made the original decision, so someone else must decide this appeal.')}</Notice>
      )}
    </div>
  );
}

export function AppealForm({ lang, item, subject, lease, busy, run }: { lang: Lang; item: QueueItem; subject: AppealSubject; lease: Lease; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const [note, setNote] = useState('');
  if (subject.state !== 'received' && subject.state !== 'in_review') return null;
  const decide = (outcome: 'upheld' | 'overturned') =>
    run(async () => {
      const result = await decideAppeal(subject.appeal_id, { outcome, expectedVersion: subject.version, note: note.trim(), taskId: item.id, leaseToken: lease.token });
      return t(`আপিল: ${result.state}`, `Appeal: ${result.state}`);
    });
  return (
    <fieldset className="stack decision">
      <legend>{t('আপিলের সিদ্ধান্ত', 'Appeal decision')}</legend>
      <label htmlFor="appeal-note">{t('কারণ (আবেদনকারী দেখবেন)', 'Reason (the appellant sees it)')}</label>
      <textarea id="appeal-note" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row">
        <button type="button" className="ghost" disabled={busy || note.trim().length < 3} onClick={() => void decide('upheld')}>
          {t('মূল সিদ্ধান্ত বহাল', 'Uphold')}
        </button>
        <button type="button" className="primary" disabled={busy || note.trim().length < 3} onClick={() => void decide('overturned')}>
          {t('মূল সিদ্ধান্ত বাতিল', 'Overturn')}
        </button>
      </div>
    </fieldset>
  );
}

// ---------------- enforcement ----------------

export function EnforcementBody({ subject, lang }: { subject: EnforcementSubject; lang: Lang }) {
  const t = makeT(lang);
  return (
    <div className="content-box">
      <div className="row small muted">
        <span className="tag">{subject.state}</span>
        {subject.emergency && <span className="tag warn">{t('জরুরি', 'Emergency')}</span>}
        <span>{subject.reason_code}</span>
        {subject.follow_up_due_at && (
          <span>
            {t('পর্যালোচনার শেষ সময়', 'Review by')}: {new Date(subject.follow_up_due_at).toLocaleString()}
          </span>
        )}
      </div>
      {subject.review && <p className="content-text">{subject.review.title}</p>}
      {subject.user && (
        <p className="content-text">
          {subject.user.display_name} · {subject.user.email}
        </p>
      )}
      {subject.note && <p className="small muted">{subject.note}</p>}
    </div>
  );
}

export function EnforcementFollowUp({ lang, subject, busy, run }: { lang: Lang; subject: EnforcementSubject; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const actions = enforcementActions(subject.state);
  const act = (action: 'remove' | 'restore' | 'close') =>
    run(async () => {
      const result = await enforcementAction(subject.case_id, { action, expected_version: subject.version, reason_code: action === 'restore' ? 'follow-up-restore' : 'follow-up-confirmed', counts_toward_rating: action === 'remove' ? false : undefined });
      return t(`অবস্থা: ${result.state}`, `State: ${result.state}`);
    });
  return (
    <div className="row">
      {actions.map((action) => (
        <button key={action} type="button" className={action === 'restore' ? 'ghost' : 'primary'} disabled={busy} onClick={() => void act(action)}>
          {action === 'remove' ? t('অপসারণ নিশ্চিত', 'Confirm removal') : action === 'restore' ? t('ফিরিয়ে আনুন', 'Restore') : t('বন্ধ করুন', 'Close')}
        </button>
      ))}
    </div>
  );
}
