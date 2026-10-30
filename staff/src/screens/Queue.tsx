import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { assignTask, claimTask, decide, escalateTask, getQueue, getStaff, heartbeatTask, releaseTask, reviewMediaUrl, transitionReport } from '../api';
import {
  REASONS,
  REPORT_REASONS,
  REPORT_RESOLUTIONS,
  RELOAD_CODES,
  decisionsFor,
  errorText,
  QUEUE_POLL_MS,
  formatCountdown,
  keepFresh,
  newIdempotencyKey,
  reportMoves,
  secondsLeft,
  DECISION_LABEL,
  type Decision,
  type ReportMove,
} from '../logic';
import { StaffError } from '../api';
import type { Lang, QueueItem, ReportSubject, ReviewMedia, ReviewSubject, Role } from '../types';
import { Notice, makeT } from '../ui';
import { AppealBody, AppealForm, EnforcementBody, EnforcementFollowUp, VerificationBody, VerificationForm } from './CaseForms';

interface Props {
  lang: Lang;
  role: Role;
  userId: string;
}

interface Lease {
  token: string;
  expiresAt: string;
}

const HEARTBEAT_MS = 60_000;

/** The work queue: pick a task, claim it (a 5-minute lease), decide, and the next one appears. */
export function Queue({ lang, role, userId }: Props) {
  const t = makeT(lang);
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [filter, setFilter] = useState<'all' | QueueItem['task_type']>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [leases, setLeases] = useState<Record<string, Lease>>({});
  const [now, setNow] = useState(() => Date.now());
  const [message, setMessage] = useState<{ tone: 'error' | 'success' | 'info'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const leasesRef = useRef(leases);
  leasesRef.current = leases;

  const load = useCallback(async () => {
    try {
      const answer = await getQueue(filter === 'all' ? undefined : filter);
      setItems(answer.items);
      // A lease this person already holds (page reload, second tab) is picked up from the queue.
      setLeases((current) => {
        const next = { ...current };
        for (const item of answer.items) {
          if (item.lease_token && item.claimed_by === userId && item.lease_expires_at) next[item.id] = { token: item.lease_token, expiresAt: item.lease_expires_at };
          if (!item.lease_active && next[item.id]) delete next[item.id];
        }
        return next;
      });
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  }, [filter, lang, userId]);

  // A new review must reach a moderator within seconds: poll often while visible, refresh on focus.
  useEffect(() => keepFresh(() => void load(), QUEUE_POLL_MS), [load]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  // Keep every lease this person holds alive while the page is open.
  useEffect(() => {
    const beat = window.setInterval(() => {
      for (const [taskId, lease] of Object.entries(leasesRef.current)) {
        heartbeatTask(taskId, lease.token)
          .then((task) => task.lease_expires_at && setLeases((current) => ({ ...current, [taskId]: { token: lease.token, expiresAt: task.lease_expires_at as string } })))
          .catch(() => {
            setLeases((current) => {
              const next = { ...current };
              delete next[taskId];
              return next;
            });
          });
      }
    }, HEARTBEAT_MS);
    return () => window.clearInterval(beat);
  }, []);

  const selected = useMemo(() => items?.find((item) => item.id === selectedId) ?? null, [items, selectedId]);

  /** Runs one action; a "reload" error drops the lease and refreshes, any error is shown plainly. */
  const run = async (work: () => Promise<string | void>) => {
    setBusy(true);
    setMessage(null);
    try {
      const done = await work();
      if (done) setMessage({ tone: 'success', text: done });
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
      if (failure instanceof StaffError && RELOAD_CODES.has(failure.code) && selectedId) {
        setLeases((current) => {
          const next = { ...current };
          delete next[selectedId];
          return next;
        });
      }
    } finally {
      setBusy(false);
      await load();
    }
  };

  const claim = (item: QueueItem) =>
    run(async () => {
      const task = await claimTask(item.id);
      if (task.lease_token && task.lease_expires_at) setLeases((current) => ({ ...current, [item.id]: { token: task.lease_token as string, expiresAt: task.lease_expires_at as string } }));
      return t('কাজটি আপনার দখলে। ৫ মিনিটের লিজ চলছে।', 'You hold this task. A 5-minute lease is running.');
    });

  const release = (item: QueueItem) =>
    run(async () => {
      const lease = leases[item.id];
      if (!lease) return;
      await releaseTask(item.id, lease.token);
      setLeases((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      return t('কাজটি ছেড়ে দেওয়া হয়েছে।', 'Task released.');
    });

  const escalate = (item: QueueItem, reason: string) =>
    run(async () => {
      const lease = leases[item.id];
      if (!lease) return;
      await escalateTask(item.id, lease.token, reason);
      setLeases((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      return t('কাজটি সুপারঅ্যাডমিনের কাছে পাঠানো হয়েছে।', 'Escalated to a superadmin.');
    });

  return (
    <div className="queue-layout">
      <section className="card list-pane" aria-label={t('কাজের তালিকা', 'Task list')}>
        <div className="row between">
          <h2>{t('কাজের সারি', 'Work queue')}</h2>
          <button type="button" className="ghost" onClick={() => void load()}>
            {t('রিফ্রেশ', 'Refresh')}
          </button>
        </div>
        <div className="segmented" role="group" aria-label={t('ধরন', 'Type')}>
          {(['all', 'review_moderation', 'report', 'verification', 'appeal', 'enforcement'] as const).map((value) => (
            <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>
              {value === 'all' ? t('সব', 'All') : t(...TYPE_LABEL[value])}
            </button>
          ))}
        </div>
        {items === null && <p className="muted">{t('লোড হচ্ছে…', 'Loading…')}</p>}
        {items?.length === 0 && <p className="muted">{t('কোনো খোলা কাজ নেই।', 'No open tasks.')}</p>}
        <ul className="list">
          {items?.map((item) => {
            const lease = leases[item.id];
            return (
              <li key={item.id}>
                <button type="button" className={`item ${item.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(item.id)}>
                  <span className="item-title">{itemTitle(item, t)}</span>
                  <span className="row small muted">
                    <span className="tag">{t(...TYPE_LABEL[item.task_type])}</span>
                    {item.escalated && <span className="tag warn">{t('উপরে পাঠানো', 'Escalated')}</span>}
                    {lease ? (
                      <span className="tag ok">{t('আপনার দখলে', 'Yours')} {formatCountdown(secondsLeft(lease.expiresAt, now))}</span>
                    ) : item.lease_active ? (
                      <span className="tag">{t('অন্যের দখলে', 'Held by someone')}</span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card detail-pane" aria-label={t('বিস্তারিত', 'Details')}>
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        {!selected && <p className="muted">{t('বাম থেকে একটি কাজ বেছে নিন।', 'Pick a task on the left.')}</p>}
        {selected && (
          <Detail
            key={selected.id}
            lang={lang}
            role={role}
            item={selected}
            lease={leases[selected.id]}
            now={now}
            busy={busy}
            onClaim={() => void claim(selected)}
            onRelease={() => void release(selected)}
            onEscalate={(reason) => void escalate(selected, reason)}
            run={run}
          />
        )}
      </section>
    </div>
  );
}

function itemTitle(item: QueueItem, t: (bn: string, en: string) => string): string {
  const subject = item.subject;
  if (!subject) return item.subject_id.slice(0, 8);
  switch (subject.kind) {
    case 'review':
      return subject.title;
    case 'report':
      return `${t('রিপোর্ট', 'Report')}: ${subject.review_title ?? subject.review_id.slice(0, 8)}`;
    case 'verification':
      return `${t('যাচাই', 'Verification')}: ${subject.applicant?.display_name ?? subject.case_id.slice(0, 8)}`;
    case 'appeal':
      return `${t('আপিল', 'Appeal')} #${subject.reference}`;
    case 'enforcement':
      return `${t('জরুরি টেকডাউন', 'Emergency takedown')}: ${subject.review?.title ?? subject.user?.display_name ?? subject.case_id.slice(0, 8)}`;
  }
}

const TYPE_LABEL: Record<QueueItem['task_type'], [string, string]> = {
  review_moderation: ['রিভিউ', 'Review'],
  report: ['রিপোর্ট', 'Report'],
  verification: ['যাচাই', 'Verification'],
  appeal: ['আপিল', 'Appeal'],
  enforcement: ['এনফোর্সমেন্ট', 'Enforcement'],
};

interface DetailProps {
  lang: Lang;
  role: Role;
  item: QueueItem;
  lease: Lease | undefined;
  now: number;
  busy: boolean;
  onClaim: () => void;
  onRelease: () => void;
  onEscalate: (reason: string) => void;
  run: (work: () => Promise<string | void>) => Promise<void>;
}

function Detail({ lang, role, item, lease, now, busy, onClaim, onRelease, onEscalate, run }: DetailProps) {
  const t = makeT(lang);
  const subject = item.subject;
  const left = secondsLeft(lease?.expiresAt, now);
  const canClaim = !lease && item.claimable && (item.required_role === 'moderator' || role === 'superadmin');

  return (
    <div className="stack">
      <div className="row between">
        <h2>{itemTitle(item, t)}</h2>
        <span className="tag">{t('সংস্করণ', 'v')}{item.version}</span>
      </div>
      <p className="muted small">
        {t('ধাপ', 'Task')} {item.id.slice(0, 8)} · {t('প্রয়োজনীয় ভূমিকা', 'needs')}: {item.required_role}
        {item.escalated && ` · ${t('উপরে পাঠানো', 'escalated')}`}
      </p>

      {subject?.kind === 'review' && <ReviewBody subject={subject} lang={lang} />}
      {subject?.kind === 'report' && <ReportBody subject={subject} lang={lang} />}
      {subject?.kind === 'verification' && <VerificationBody subject={subject} lang={lang} canView={Boolean(lease) || role === 'superadmin'} run={run} />}
      {subject?.kind === 'appeal' && <AppealBody subject={subject} lang={lang} />}
      {subject?.kind === 'enforcement' && <EnforcementBody subject={subject} lang={lang} />}
      {!subject && <Notice tone="info">{t('এই কাজের বিষয়বস্তু আর নেই।', 'The content of this task is gone.')}</Notice>}

      {role === 'superadmin' && !lease && <AssignControl lang={lang} item={item} busy={busy} run={run} />}

      {!lease && (
        <div className="row">
          <button type="button" className="primary" disabled={busy || !canClaim} onClick={onClaim}>
            {t('কাজটি নিন', 'Claim this task')}
          </button>
          {!canClaim && <span className="muted small">{item.lease_active ? t('অন্য কেউ করছেন', 'Another person holds it') : t('আপনার ভূমিকায় নেওয়া যাবে না', 'Not available to your role')}</span>}
        </div>
      )}

      {lease && subject && (
        <>
          <div className="row between lease-bar">
            <span>
              {t('আপনার লিজ', 'Your lease')}: <strong>{formatCountdown(left)}</strong>
              {left !== null && left < 60 && <span className="warn-text"> · {t('শীঘ্রই শেষ', 'ending soon')}</span>}
            </span>
            <span className="row">
              <button type="button" className="ghost" disabled={busy} onClick={onRelease}>
                {t('ছেড়ে দিন', 'Release')}
              </button>
              {role === 'moderator' && <EscalateForm lang={lang} busy={busy} onEscalate={onEscalate} />}
            </span>
          </div>
          {subject.kind === 'review' && <DecisionForm lang={lang} item={item} subject={subject} lease={lease} busy={busy} run={run} />}
          {subject.kind === 'report' && <ReportForm lang={lang} item={item} subject={subject} lease={lease} busy={busy} run={run} />}
          {subject.kind === 'verification' && <VerificationForm lang={lang} role={role} item={item} subject={subject} lease={lease} busy={busy} run={run} />}
          {subject.kind === 'appeal' && <AppealForm lang={lang} item={item} subject={subject} lease={lease} busy={busy} run={run} />}
          {subject.kind === 'enforcement' && <EnforcementFollowUp lang={lang} subject={subject} busy={busy} run={run} />}
        </>
      )}
    </div>
  );
}

/** Superadmin: give the task to one staff member (they are notified) or back to the shared queue. */
function AssignControl({ lang, item, busy, run }: { lang: Lang; item: QueueItem; busy: boolean; run: (work: () => Promise<string | void>) => Promise<void> }) {
  const t = makeT(lang);
  const [staff, setStaff] = useState<{ user_id: string; display_name: string; role: string }[] | null>(null);
  const [choice, setChoice] = useState(item.assigned_to ?? '');

  useEffect(() => {
    getStaff().then((answer) => setStaff(answer.items)).catch(() => setStaff([]));
  }, []);

  return (
    <div className="row small">
      <label htmlFor={`assign-${item.id}`}>{t('দায়িত্ব দিন', 'Assign to')}</label>
      <select id={`assign-${item.id}`} value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy || staff === null}>
        <option value="">{t('সাধারণ সারি', 'Shared queue')}</option>
        {(staff ?? []).map((member) => (
          <option key={member.user_id} value={member.user_id}>
            {member.display_name} ({member.role})
          </option>
        ))}
      </select>
      <button
        type="button"
        className="ghost"
        disabled={busy || choice === (item.assigned_to ?? '')}
        onClick={() =>
          void run(async () => {
            await assignTask(item.id, choice || null);
            return choice ? t('দায়িত্ব দেওয়া হয়েছে; তাঁকে জানানো হয়েছে।', 'Assigned; they have been notified.') : t('সাধারণ সারিতে ফেরত।', 'Back in the shared queue.');
          })
        }
      >
        {t('সংরক্ষণ', 'Save')}
      </button>
    </div>
  );
}

function ReviewBody({ subject, lang }: { subject: ReviewSubject; lang: Lang }) {
  const t = makeT(lang);
  return (
    <div className="content-box">
      <div className="row small muted">
        <span className="tag">{subject.status}</span>
        <span>{'★'.repeat(subject.overall_rating)}</span>
        <span>
          {subject.author === 'guest' ? t('অতিথি', 'Guest') : t('সদস্য', 'Member')}
          {subject.guest_display_name ? ` · ${subject.guest_display_name}` : ''}
          {subject.author_display_name ? ` · ${subject.author_display_name}` : ''}
        </span>
      </div>
      <p className="content-text">{subject.body}</p>
      {subject.media && subject.media.length > 0 && <MediaPreview reviewId={subject.review_id} media={subject.media} lang={lang} />}
    </div>
  );
}

/** Photos and video load only when asked for, through five-minute links. */
function MediaPreview({ reviewId, media, lang }: { reviewId: string; media: ReviewMedia[]; lang: Lang }) {
  const t = makeT(lang);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState<string | null>(null);

  const show = async (item: ReviewMedia) => {
    setFailed(null);
    try {
      const link = await reviewMediaUrl(reviewId, item.id);
      setUrls((current) => ({ ...current, [item.id]: link.url }));
    } catch (error) {
      setFailed(error instanceof StaffError ? error.message : t('খোলা যায়নি।', 'Could not open it.'));
    }
  };

  return (
    <div className="stack">
      <strong className="small">{t(`ছবি ও ভিডিও (${media.length})`, `Photos and video (${media.length})`)}</strong>
      {failed && <Notice tone="error">{failed}</Notice>}
      <ul className="media-list">
        {media.map((item) => (
          <li key={item.id} className="media-item">
            {urls[item.id] ? (
              item.kind === 'image' ? (
                <img src={urls[item.id]} alt={item.alt_text} className="media-preview" />
              ) : (
                <video src={urls[item.id]} controls preload="metadata" className="media-preview" />
              )
            ) : (
              <button type="button" onClick={() => void show(item)}>
                {item.kind === 'image' ? t('ছবি দেখুন', 'Show photo') : t('ভিডিও দেখুন', 'Show video')}
              </button>
            )}
            <span className="small muted">
              {item.alt_text}
              {item.caption ? ` — ${item.caption}` : ''}
              {item.duration_ms ? ` · ${Math.round(item.duration_ms / 1000)} s` : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportBody({ subject, lang }: { subject: ReportSubject; lang: Lang }) {
  const t = makeT(lang);
  const reason = REPORT_REASONS[subject.reason_code];
  return (
    <div className="stack">
      <div className="content-box">
        <div className="row small muted">
          <span className="tag">{subject.state}</span>
          <span>
            {t('কারণ', 'Reason')}: {reason ? (lang === 'bn' ? reason.bn : reason.en) : subject.reason_code}
          </span>
        </div>
        {subject.details && <p className="content-text">{subject.details}</p>}
      </div>
      <div className="content-box">
        <div className="row small muted">
          <span className="tag">{subject.review_status ?? '—'}</span>
          <span>{t('রিপোর্ট করা রিভিউ', 'Reported review')}</span>
        </div>
        <strong>{subject.review_title}</strong>
        <p className="content-text">{subject.review_body}</p>
      </div>
    </div>
  );
}

function EscalateForm({ lang, busy, onEscalate }: { lang: Lang; busy: boolean; onEscalate: (reason: string) => void }) {
  const t = makeT(lang);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  if (!open)
    return (
      <button type="button" className="ghost" disabled={busy} onClick={() => setOpen(true)}>
        {t('উপরে পাঠান', 'Escalate')}
      </button>
    );
  return (
    <span className="row">
      <input aria-label={t('কারণ', 'Reason')} placeholder={t('কারণ (৩+ অক্ষর)', 'Reason (3+ characters)')} value={reason} onChange={(e) => setReason(e.target.value)} />
      <button type="button" className="primary" disabled={busy || reason.trim().length < 3} onClick={() => onEscalate(reason.trim())}>
        {t('পাঠান', 'Send')}
      </button>
    </span>
  );
}

interface FormProps {
  lang: Lang;
  item: QueueItem;
  lease: Lease;
  busy: boolean;
  run: (work: () => Promise<string | void>) => Promise<void>;
}

function DecisionForm({ lang, item, subject, lease, busy, run }: FormProps & { subject: ReviewSubject }) {
  const t = makeT(lang);
  const options = decisionsFor(subject.status);
  const [decision, setDecision] = useState<Decision | null>(options[0] ?? null);
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [rejectedMedia, setRejectedMedia] = useState<string[]>([]);
  const key = useRef<string | null>(null);

  if (options.length === 0) return <Notice tone="info">{t('এই অবস্থায় কোনো সিদ্ধান্ত নেওয়া যায় না।', 'No decision is possible in this state.')}</Notice>;
  const media = subject.media ?? [];
  const reasons = decision ? REASONS[decision] : [];
  const chosenReason = reason || reasons[0]?.code || '';

  const submit = () =>
    run(async () => {
      if (!decision) return;
      key.current ??= newIdempotencyKey(); // a retry of this same attempt reuses the key
      try {
        const result = await decide(
          subject.review_id,
          {
            taskId: item.id,
            leaseToken: lease.token,
            expectedVersion: subject.version,
            decision,
            reasonCode: chosenReason,
            note,
            rejectedMediaIds: decision === 'PUBLISH' ? rejectedMedia : undefined,
          },
          key.current,
        );
        key.current = null;
        return t(`সম্পন্ন: ${result.status}`, `Done: ${result.status}`);
      } catch (failure) {
        if (!(failure instanceof StaffError) || failure.code !== 'NETWORK_ERROR') key.current = null; // only a lost response is retried with the same key
        throw failure;
      }
    });

  return (
    <fieldset className="stack decision">
      <legend>{t('সিদ্ধান্ত', 'Decision')}</legend>
      <div className="segmented" role="group">
        {options.map((option) => (
          <button key={option} type="button" aria-pressed={decision === option} onClick={() => { setDecision(option); setReason(''); }}>
            {t(DECISION_LABEL[option].bn, DECISION_LABEL[option].en)}
          </button>
        ))}
      </div>
      <label htmlFor="reason-code">{t('কারণ', 'Reason')}</label>
      <select id="reason-code" value={chosenReason} onChange={(e) => setReason(e.target.value)}>
        {reasons.map((r) => (
          <option key={r.code} value={r.code}>
            {lang === 'bn' ? r.bn : r.en}
          </option>
        ))}
      </select>
      {decision === 'PUBLISH' && media.length > 0 && (
        <fieldset className="stack">
          <legend className="small">{t('রিভিউর সাথে প্রকাশ হবে (না চাইলে টিক তুলে দিন)', 'Published with the review (untick any that must not be shown)')}</legend>
          {media.map((m) => (
            <label key={m.id} className="row small">
              <input
                type="checkbox"
                checked={!rejectedMedia.includes(m.id)}
                onChange={(e) => setRejectedMedia((ids) => (e.target.checked ? ids.filter((id) => id !== m.id) : [...ids, m.id]))}
              />
              {t('প্রকাশ করুন', 'Publish')} {m.kind === 'image' ? t('ছবি', 'photo') : t('ভিডিও', 'video')}: {m.alt_text}
            </label>
          ))}
          {rejectedMedia.length > 0 && (
            <p className="small">{t(`${rejectedMedia.length}টি প্রকাশ হবে না।`, `${rejectedMedia.length} will not be published.`)}</p>
          )}
        </fieldset>
      )}
      {decision === 'REQUEST_CHANGES' && (
        <p className="small muted">
          {t('লেখক কারণটি দেখতে পাবেন এবং সম্পাদনা করে আবার জমা দিতে পারবেন। কারণে কোনো ব্যক্তিগত তথ্য লিখবেন না।', 'The author can read the reason and edit the review to send it back. Do not put private details in the reason.')}
        </p>
      )}
      {decision === 'REJECT' && media.length > 0 && (
        <p className="small muted">{t('রিভিউ বাতিল হলে সব ছবি ও ভিডিও বাতিল হবে।', 'Rejecting the review rejects all its photos and video.')}</p>
      )}
      <label htmlFor="decision-note">{t('নোট (ঐচ্ছিক)', 'Note (optional)')}</label>
      <textarea id="decision-note" rows={3} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="button" className="primary" disabled={busy || !decision} onClick={() => void submit()}>
        {busy ? '…' : t('সিদ্ধান্ত জমা দিন', 'Submit decision')}
      </button>
    </fieldset>
  );
}

function ReportForm({ lang, item, subject, lease, busy, run }: FormProps & { subject: ReportSubject }) {
  const t = makeT(lang);
  const moves = reportMoves(subject.state);
  const [note, setNote] = useState('');
  const hideOptions = subject.review_status ? decisionsFor(subject.review_status).filter((d) => d === 'HIDE' || d === 'RESTORE') : [];
  const key = useRef<string | null>(null);

  const move = (to: ReportMove) =>
    run(async () => {
      await transitionReport(subject.report_id, { taskId: item.id, leaseToken: lease.token, expectedVersion: subject.version, to, reasonCode: REPORT_RESOLUTIONS[to].code, note });
      return t('রিপোর্ট হালনাগাদ হয়েছে।', 'Report updated.');
    });

  const hide = (decision: Decision) =>
    run(async () => {
      key.current ??= newIdempotencyKey();
      try {
        await decide(subject.review_id, { taskId: item.id, leaseToken: lease.token, expectedVersion: subject.review_version ?? 1, decision, reasonCode: REASONS[decision][0].code, note }, key.current);
        key.current = null;
        return t('রিভিউর অবস্থা বদলেছে।', 'The review was changed.');
      } catch (failure) {
        if (!(failure instanceof StaffError) || failure.code !== 'NETWORK_ERROR') key.current = null;
        throw failure;
      }
    });

  return (
    <fieldset className="stack decision">
      <legend>{t('রিপোর্টের সিদ্ধান্ত', 'Report decision')}</legend>
      <label htmlFor="report-note">{t('নোট (ঐচ্ছিক)', 'Note (optional)')}</label>
      <textarea id="report-note" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {hideOptions.length > 0 && (
        <div className="row">
          {hideOptions.map((option) => (
            <button key={option} type="button" className="ghost" disabled={busy} onClick={() => void hide(option)}>
              {option === 'HIDE' ? t('রিভিউ লুকান', 'Hide the review') : t('রিভিউ ফিরিয়ে আনুন', 'Restore the review')}
            </button>
          ))}
        </div>
      )}
      <div className="row">
        {moves.map((to) => (
          <button key={to} type="button" className={to === 'in_review' ? 'ghost' : 'primary'} disabled={busy} onClick={() => void move(to)}>
            {lang === 'bn' ? REPORT_RESOLUTIONS[to].bn : REPORT_RESOLUTIONS[to].en}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
