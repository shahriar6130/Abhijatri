import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  activateTemplateVersion,
  addSuppression,
  createTemplateVersion,
  getDeliveries,
  getDelivery,
  getOutbox,
  getSuppressions,
  getTemplateVersions,
  getTemplates,
  removeSuppression,
  retryDelivery,
  updateRule,
} from '../api';
import { errorText } from '../logic';
import type { DeliveryDetail, DeliveryRow, Lang, OutboxRow, SuppressionRow, TemplateKey, TemplateVersion } from '../types';
import { Notice, makeT } from '../ui';

type Section = 'deliveries' | 'outbox' | 'suppressions' | 'templates';
type Run = (work: () => Promise<string | void>) => Promise<void>;

/**
 * Superadmin operations of the notification system (Notification spec 9 and 12): outbox, deliveries
 * with their attempt history and retry, suppressions, and versioned templates and rules. Addresses
 * are never shown, only a prefix of their HMAC. Every change here is written to the audit log.
 */
export function Notifications({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [section, setSection] = useState<Section>('deliveries');
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const run: Run = async (work) => {
    setBusy(true);
    setMessage(null);
    try {
      const done = await work();
      if (done) setMessage({ tone: 'success', text: done });
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    } finally {
      setBusy(false);
    }
  };

  const sections: [Section, string][] = [
    ['deliveries', t('ইমেইল ডেলিভারি', 'Deliveries')],
    ['outbox', t('আউটবক্স', 'Outbox')],
    ['suppressions', t('বাদ দেওয়া ঠিকানা', 'Suppressions')],
    ['templates', t('টেমপ্লেট ও নিয়ম', 'Templates and rules')],
  ];

  return (
    <section className="stack">
      <h2>{t('বিজ্ঞপ্তি ব্যবস্থা', 'Notification system')}</h2>
      <div className="segmented" role="group">
        {sections.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={section === id} onClick={() => setSection(id)}>
            {label}
          </button>
        ))}
      </div>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {section === 'deliveries' && <Deliveries lang={lang} busy={busy} run={run} />}
      {section === 'outbox' && <Outbox lang={lang} />}
      {section === 'suppressions' && <Suppressions lang={lang} busy={busy} run={run} />}
      {section === 'templates' && <Templates lang={lang} busy={busy} run={run} />}
    </section>
  );
}

const when = (value: string | null) => (value ? new Date(value).toLocaleString() : '—');

function Deliveries({ lang, busy, run }: { lang: Lang; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const [status, setStatus] = useState('');
  const [data, setData] = useState<{ items: DeliveryRow[]; counts: Record<string, number> } | null>(null);
  const [open, setOpen] = useState<DeliveryDetail | null>(null);
  const [reason, setReason] = useState('');

  const load = useCallback(() => {
    getDeliveries(status || undefined).then(setData).catch(() => setData({ items: [], counts: {} }));
  }, [status]);

  useEffect(load, [load]);

  return (
    <div className="stack">
      <div className="row small">
        <label htmlFor="delivery-status">{t('অবস্থা', 'Status')}</label>
        <select id="delivery-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t('সব', 'All')}</option>
          {['queued', 'sending', 'accepted', 'delivered', 'bounced', 'failed_permanently', 'skipped', 'ambiguous'].map((s) => (
            <option key={s} value={s}>
              {s} ({data?.counts[s] ?? 0})
            </option>
          ))}
        </select>
      </div>
      <div className="table-wrap"><table className="small">
        <thead>
          <tr>
            <th>{t('ধরন', 'Kind')}</th>
            <th>{t('অবস্থা', 'Status')}</th>
            <th>{t('চেষ্টা', 'Tries')}</th>
            <th>{t('ত্রুটি', 'Error')}</th>
            <th>{t('হালনাগাদ', 'Updated')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data?.items.map((row) => (
            <tr key={row.id}>
              <td>{row.kind ?? t('সারসংক্ষেপ', 'digest')}</td>
              <td>{row.status}</td>
              <td>{row.attempt_count}</td>
              <td>{row.last_error_code ?? ''}</td>
              <td>{when(row.updated_at)}</td>
              <td>
                <button type="button" className="ghost" onClick={() => void getDelivery(row.id).then(setOpen)}>
                  {t('বিস্তারিত', 'Details')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {data && data.items.length === 0 && <Notice tone="info">{t('কিছু নেই।', 'Nothing here.')}</Notice>}
      {open && (
        <div className="content-box stack">
          <strong>
            {open.kind ?? t('সারসংক্ষেপ', 'digest')} · {open.status} · {t('ঠিকানা-রেফ', 'address ref')} {open.destination_ref ?? '—'}
          </strong>
          {open.last_error_summary && <span className="small muted">{open.last_error_summary}</span>}
          <ol className="small">
            {open.attempts.map((a) => (
              <li key={a.attempt_number}>
                #{a.attempt_number} {a.outcome} {a.error_code ? `(${a.error_code})` : ''} · {when(a.started_at)}
              </li>
            ))}
          </ol>
          {(open.status === 'ambiguous' || open.status === 'failed_permanently') && (
            <div className="row">
              <input placeholder={t('কেন আবার পাঠাবেন (আবশ্যক)', 'Why send again (required)')} value={reason} onChange={(e) => setReason(e.target.value)} />
              <button
                type="button"
                className="primary"
                disabled={busy || reason.trim().length < 3}
                onClick={() =>
                  void run(async () => {
                    await retryDelivery(open.id, reason.trim());
                    setOpen(null);
                    setReason('');
                    load();
                    return t('আবার পাঠানোর সারিতে।', 'Queued to send again.');
                  })
                }
              >
                {t('আবার পাঠান', 'Retry')}
              </button>
            </div>
          )}
          {open.status === 'ambiguous' && (
            <span className="small warn-text">
              {t('অস্পষ্ট: ইমেইল সেবা হয়তো আগেই পাঠিয়েছে। আবার পাঠানোর আগে তাদের ড্যাশবোর্ডে দেখুন।', 'Unclear: the provider may already have sent it. Check its dashboard before retrying.')}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function Outbox({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [status, setStatus] = useState('');
  const [data, setData] = useState<{ items: OutboxRow[]; counts: Record<string, number>; oldest_unprocessed_at: string | null } | null>(null);

  useEffect(() => {
    getOutbox(status || undefined).then(setData).catch(() => setData(null));
  }, [status]);

  return (
    <div className="stack">
      <div className="row small">
        <label htmlFor="outbox-status">{t('অবস্থা', 'Status')}</label>
        <select id="outbox-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t('সব', 'All')}</option>
          {['pending', 'processing', 'retry', 'processed', 'dead_letter'].map((s) => (
            <option key={s} value={s}>
              {s} ({data?.counts[s] ?? 0})
            </option>
          ))}
        </select>
        <span className="muted">
          {t('সবচেয়ে পুরোনো অপ্রক্রিয়াজাত', 'Oldest unprocessed')}: {when(data?.oldest_unprocessed_at ?? null)}
        </span>
      </div>
      <div className="table-wrap"><table className="small">
        <thead>
          <tr>
            <th>{t('ঘটনা', 'Event')}</th>
            <th>{t('অবস্থা', 'Status')}</th>
            <th>{t('চেষ্টা', 'Tries')}</th>
            <th>{t('ত্রুটি', 'Error')}</th>
            <th>{t('তৈরি', 'Created')}</th>
          </tr>
        </thead>
        <tbody>
          {data?.items.map((row) => (
            <tr key={row.id}>
              <td>{row.event_type}</td>
              <td>{row.status}</td>
              <td>{row.attempts}</td>
              <td>{row.last_error_code ?? ''}</td>
              <td>{when(row.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function Suppressions({ lang, busy, run }: { lang: Lang; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const [items, setItems] = useState<SuppressionRow[]>([]);
  const [email, setEmail] = useState('');
  const [reason, setReason] = useState('');
  const [removal, setRemoval] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    getSuppressions().then((answer) => setItems(answer.items)).catch(() => setItems([]));
  }, []);

  useEffect(load, [load]);

  const add = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await addSuppression(email.trim(), reason.trim());
      setEmail('');
      setReason('');
      load();
      return t('ঠিকানাটিতে আর ইমেইল যাবে না।', 'That address will not be emailed.');
    });
  };

  return (
    <div className="stack">
      <form className="row" onSubmit={add}>
        <input type="email" required placeholder={t('ইমেইল ঠিকানা', 'Email address')} value={email} onChange={(e) => setEmail(e.target.value)} />
        <input required minLength={2} placeholder={t('কারণ কোড', 'Reason code')} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="submit" className="primary" disabled={busy}>
          {t('যোগ করুন', 'Add')}
        </button>
      </form>
      <p className="small muted">{t('ঠিকানা সংরক্ষণ হয় না, শুধু তার HMAC।', 'The address is not stored, only its HMAC.')}</p>
      <ul className="stack">
        {items.map((row) => (
          <li key={row.id} className="content-box row between small">
            <span>
              {row.destination_ref}… · {row.reason_code} · {when(row.created_at)}
            </span>
            <span className="row">
              <input
                placeholder={t('সরানোর কারণ', 'Reason to remove')}
                value={removal[row.id] ?? ''}
                onChange={(e) => setRemoval((current) => ({ ...current, [row.id]: e.target.value }))}
              />
              <button
                type="button"
                className="ghost"
                disabled={busy || (removal[row.id] ?? '').trim().length < 3}
                onClick={() =>
                  void run(async () => {
                    await removeSuppression(row.id, (removal[row.id] ?? '').trim());
                    load();
                    return t('সরানো হয়েছে।', 'Removed.');
                  })
                }
              >
                {t('সরান', 'Remove')}
              </button>
            </span>
          </li>
        ))}
      </ul>
      {items.length === 0 && <Notice tone="info">{t('কোনো সক্রিয় বাদ-তালিকা নেই।', 'No active suppressions.')}</Notice>}
    </div>
  );
}

function Templates({ lang, busy, run }: { lang: Lang; busy: boolean; run: Run }) {
  const t = makeT(lang);
  const [keys, setKeys] = useState<TemplateKey[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [versions, setVersions] = useState<TemplateVersion[]>([]);
  const [draft, setDraft] = useState<{ channel: 'in_app' | 'email'; locale: 'bn' | 'en'; title: string; body: string }>({ channel: 'in_app', locale: 'en', title: '', body: '' });

  const loadKeys = useCallback(() => {
    getTemplates().then((answer) => setKeys(answer.items)).catch(() => setKeys([]));
  }, []);
  const loadVersions = useCallback(() => {
    if (selected) getTemplateVersions(selected).then((answer) => setVersions(answer.items)).catch(() => setVersions([]));
  }, [selected]);

  useEffect(loadKeys, [loadKeys]);
  useEffect(loadVersions, [loadVersions]);

  const current = keys.find((k) => k.template_key === selected);

  return (
    <div className="stack">
      <div className="row small">
        <label htmlFor="template-key">{t('টেমপ্লেট', 'Template')}</label>
        <select id="template-key" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">{t('বেছে নিন', 'Choose')}</option>
          {keys.map((k) => (
            <option key={k.template_key} value={k.template_key}>
              {k.template_key} {k.enabled ? '' : `(${t('বন্ধ', 'off')})`}
            </option>
          ))}
        </select>
      </div>
      {current && (
        <div className="content-box stack small">
          <span>
            {t('শ্রোতা', 'Audience')}: {current.audience} · {t('অগ্রাধিকার', 'Priority')}: {current.priority} · {t('ইমেইল', 'Email')}: {current.email ? t('হ্যাঁ', 'yes') : t('না', 'no')} ·{' '}
            {t('চলক', 'Variables')}: {current.variables.length ? current.variables.map((v) => `{${v}}`).join(' ') : t('নেই', 'none')}
          </span>
          <span className="row">
            <select
              aria-label={t('অগ্রাধিকার', 'Priority')}
              value={current.priority ?? 'normal'}
              disabled={busy}
              onChange={(e) => void run(async () => { await updateRule(current.template_key, { priority: e.target.value }); loadKeys(); return t('নিয়ম বদলেছে।', 'Rule changed.'); })}
            >
              {['critical', 'high', 'normal', 'low'].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <button type="button" className="ghost" disabled={busy} onClick={() => void run(async () => { await updateRule(current.template_key, { email: !current.email }); loadKeys(); return t('নিয়ম বদলেছে।', 'Rule changed.'); })}>
              {current.email ? t('ইমেইল বন্ধ', 'Turn email off') : t('ইমেইল চালু', 'Turn email on')}
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => void run(async () => { await updateRule(current.template_key, { enabled: !current.enabled }); loadKeys(); return t('নিয়ম বদলেছে।', 'Rule changed.'); })}>
              {current.enabled ? t('বিজ্ঞপ্তি বন্ধ', 'Disable') : t('বিজ্ঞপ্তি চালু', 'Enable')}
            </button>
          </span>
          <div className="table-wrap"><table>
            <thead>
              <tr>
                <th>{t('চ্যানেল', 'Channel')}</th>
                <th>{t('ভাষা', 'Lang')}</th>
                <th>v</th>
                <th>{t('অবস্থা', 'Status')}</th>
                <th>{t('লেখা', 'Text')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td>{v.channel}</td>
                  <td>{v.locale}</td>
                  <td>{v.version}</td>
                  <td>{v.status}</td>
                  <td>
                    <strong>{v.title_template ?? v.subject_template}</strong> {v.body_template}
                  </td>
                  <td>
                    {v.status === 'draft' && (
                      <button
                        type="button"
                        className="primary"
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await activateTemplateVersion(v.template_key, v.version, v.channel, v.locale);
                            loadVersions();
                            loadKeys();
                            return t('সক্রিয় করা হয়েছে।', 'Activated.');
                          })
                        }
                      >
                        {t('সক্রিয় করুন', 'Activate')}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                await createTemplateVersion(current.template_key, {
                  channel: draft.channel,
                  locale: draft.locale,
                  ...(draft.channel === 'in_app' ? { title_template: draft.title } : { subject_template: draft.title }),
                  body_template: draft.body,
                });
                setDraft({ ...draft, title: '', body: '' });
                loadVersions();
                return t('খসড়া তৈরি হয়েছে; সক্রিয় করলে ব্যবহার হবে।', 'Draft created; it is used once activated.');
              });
            }}
          >
            <strong>{t('নতুন সংস্করণ', 'New version')}</strong>
            <span className="row">
              <select value={draft.channel} onChange={(e) => setDraft({ ...draft, channel: e.target.value as 'in_app' | 'email' })}>
                <option value="in_app">in_app</option>
                <option value="email">email</option>
              </select>
              <select value={draft.locale} onChange={(e) => setDraft({ ...draft, locale: e.target.value as 'bn' | 'en' })}>
                <option value="en">English</option>
                <option value="bn">বাংলা</option>
              </select>
            </span>
            <input required maxLength={160} placeholder={t('শিরোনাম', 'Title')} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            <textarea required rows={3} maxLength={600} placeholder={t('লেখা; শুধু উপরের চলকগুলো', 'Body; only the variables above')} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
            <button type="submit" className="primary" disabled={busy}>
              {t('খসড়া সংরক্ষণ', 'Save draft')}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
