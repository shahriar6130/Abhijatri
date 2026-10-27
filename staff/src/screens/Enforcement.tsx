import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { enforcementAction, getEnforcementCases, openEnforcement, searchUsers, type OpenEnforcementInput } from '../api';
import { enforcementActions, errorText } from '../logic';
import type { EnforcementCase, Lang, Role, UserHit } from '../types';
import { Notice, makeT } from '../ui';

type SanctionKind = 'none' | 'warning' | 'posting_restriction' | 'suspension';

/**
 * Takedowns and account actions (Moderation spec 6.4, 7.3). Visibility, rating eligibility and
 * sanctions are separate choices; each has a reason, an actor and an audit event.
 */
export function Enforcement({ lang, role }: { lang: Lang; role: Role }) {
  const t = makeT(lang);
  const [items, setItems] = useState<EnforcementCase[] | null>(null);
  const [target, setTarget] = useState<'review' | 'user'>('review');
  const [reviewId, setReviewId] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<UserHit[]>([]);
  const [userId, setUserId] = useState('');
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [emergency, setEmergency] = useState(false);
  const [counts, setCounts] = useState(true);
  const [sanction, setSanction] = useState<SanctionKind>('none');
  const [days, setDays] = useState(7);
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems((await getEnforcementCases()).items);
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  }, [lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await work();
      setMessage({ tone: 'success', text: done });
      await load();
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const input: OpenEnforcementInput = { reason_code: reason.trim(), note: note.trim() || undefined, emergency, counts_toward_rating: counts };
    if (target === 'review') input.review_id = reviewId.trim();
    else input.user_id = userId;
    if (sanction !== 'none') input.sanction = { kind: sanction, ends_at: new Date(Date.now() + days * 86_400_000).toISOString() };
    void run(() => openEnforcement(input), t('কেস খোলা হয়েছে।', 'Case opened.'));
  };

  const find = () =>
    void run(async () => {
      setHits((await searchUsers(query.trim())).items);
    }, t('খোঁজা হয়েছে।', 'Searched.'));

  const act = (item: EnforcementCase, action: 'remove' | 'restore' | 'close') =>
    void run(
      () => enforcementAction(item.case_id, { action, expected_version: item.version, reason_code: `manual-${action}`, counts_toward_rating: action === 'remove' ? false : undefined }),
      t('হালনাগাদ হয়েছে।', 'Updated.'),
    );

  const reverse = (item: EnforcementCase, sanctionId: string) =>
    void run(() => enforcementAction(item.case_id, { action: 'reverse_sanction', expected_version: item.version, reason_code: 'manual-reverse', sanction_id: sanctionId }), t('সীমাবদ্ধতা তুলে নেওয়া হয়েছে।', 'Restriction lifted.'));

  const valid = reason.trim().length >= 2 && (target === 'review' ? /^[0-9a-f-]{36}$/i.test(reviewId.trim()) : Boolean(userId));

  return (
    <div className="stack">
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      <form className="card stack" onSubmit={submit}>
        <h2>{t('নতুন এনফোর্সমেন্ট কেস', 'New enforcement case')}</h2>
        <div className="segmented" role="group">
          <button type="button" aria-pressed={target === 'review'} onClick={() => setTarget('review')}>
            {t('রিভিউ টেকডাউন', 'Take down a review')}
          </button>
          <button type="button" aria-pressed={target === 'user'} onClick={() => setTarget('user')} disabled={role !== 'superadmin'}>
            {t('অ্যাকাউন্টে ব্যবস্থা', 'Act on an account')}
          </button>
        </div>
        {target === 'review' ? (
          <>
            <label htmlFor="enf-review">{t('রিভিউ আইডি (প্রকাশিত)', 'Review id (published)')}</label>
            <input id="enf-review" value={reviewId} onChange={(e) => setReviewId(e.target.value)} placeholder="00000000-0000-0000-0000-000000000000" />
            <label className="row small">
              <input type="checkbox" checked={counts} onChange={(e) => setCounts(e.target.checked)} />
              {t('রেটিংয়ে গণনা চলবে', 'Still counts towards ratings')}
            </label>
          </>
        ) : (
          <>
            <div className="row">
              <input aria-label={t('ইমেইল খুঁজুন', 'Search by email')} value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('ইমেইলের অংশ', 'Part of an email')} />
              <button type="button" className="ghost" disabled={query.trim().length < 3} onClick={find}>
                {t('খুঁজুন', 'Search')}
              </button>
            </div>
            {hits.length > 0 && (
              <select aria-label={t('অ্যাকাউন্ট', 'Account')} value={userId} onChange={(e) => setUserId(e.target.value)}>
                <option value="">{t('একটি বেছে নিন', 'Choose one')}</option>
                {hits.map((hit) => (
                  <option key={hit.user_id} value={hit.user_id}>
                    {hit.display_name} · {hit.email}
                  </option>
                ))}
              </select>
            )}
          </>
        )}
        <label htmlFor="enf-reason">{t('কারণ কোড', 'Reason code')}</label>
        <input id="enf-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="harassment" />
        <label htmlFor="enf-note">{t('নোট', 'Note')}</label>
        <textarea id="enf-note" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        <label className="row small">
          <input type="checkbox" checked={emergency} onChange={(e) => setEmergency(e.target.checked)} />
          {t('জরুরি (২৪ ঘণ্টার মধ্যে সুপারঅ্যাডমিন পর্যালোচনা)', 'Emergency (superadmin review within 24 hours)')}
        </label>
        <label htmlFor="enf-sanction">{t('সীমাবদ্ধতা', 'Restriction')}</label>
        <div className="row">
          <select id="enf-sanction" value={sanction} onChange={(e) => setSanction(e.target.value as SanctionKind)}>
            <option value="none">{t('নেই', 'None')}</option>
            <option value="warning">{t('সতর্কতা', 'Warning')}</option>
            <option value="posting_restriction">{t('লেখা সীমিত', 'Posting restriction')}</option>
            <option value="suspension" disabled={role !== 'superadmin'}>
              {t('স্থগিত', 'Suspension')}
            </option>
          </select>
          {sanction !== 'none' && (
            <label className="row small">
              <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 80 }} />
              {t('দিন', 'days')}
            </label>
          )}
        </div>
        <button type="submit" className="primary" disabled={busy || !valid}>
          {t('কেস খুলুন', 'Open case')}
        </button>
      </form>

      <section className="card stack">
        <h2>{t('কেসগুলো', 'Cases')}</h2>
        {items?.length === 0 && <p className="muted">{t('কোনো কেস নেই।', 'No cases.')}</p>}
        {items?.map((item) => (
          <div key={item.case_id} className="item">
            <span className="item-title">
              {item.review?.title ?? item.user?.display_name ?? item.case_id.slice(0, 8)}
            </span>
            <span className="row small muted">
              <span className="tag">{item.state}</span>
              {item.emergency && <span className="tag warn">{t('জরুরি', 'Emergency')}</span>}
              <span>{item.reason_code}</span>
              <span>{item.counts_toward_rating ? t('রেটিংয়ে গণনা', 'counts in ratings') : t('রেটিংয়ে গণনা নয়', 'not counted')}</span>
            </span>
            <span className="row">
              {enforcementActions(item.state).map((action) => (
                <button key={action} type="button" className="ghost" disabled={busy || (item.emergency && role !== 'superadmin')} onClick={() => act(item, action)}>
                  {action === 'remove' ? t('অপসারণ', 'Remove') : action === 'restore' ? t('ফিরিয়ে আনুন', 'Restore') : t('বন্ধ', 'Close')}
                </button>
              ))}
              {item.sanctions
                .filter((s) => s.state === 'active')
                .map((s) => (
                  <button key={s.id} type="button" className="ghost" disabled={busy} onClick={() => reverse(item, s.id)}>
                    {t('তুলে নিন', 'Lift')} {s.kind}
                  </button>
                ))}
            </span>
          </div>
        ))}
      </section>
    </div>
  );
}
