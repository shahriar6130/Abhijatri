import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { exportAuditCsv, getAuditActions, getAuditEvents, type AuditFilters } from '../api';
import { auditRange, errorText, isSuperadmin } from '../logic';
import type { AuditItem, Lang, Role } from '../types';
import { Notice, makeT } from '../ui';

interface FormState {
  action: string;
  target_type: string;
  target_id: string;
  actor_role: string;
  request_id: string;
  fromDay: string;
  toDay: string;
}

const EMPTY: FormState = { action: '', target_type: '', target_id: '', actor_role: '', request_id: '', fromDay: '', toDay: '' };

/** The filters the API takes, from what the form holds. Empty fields are left out. */
export function toFilters(form: FormState): AuditFilters {
  const filters: AuditFilters = { ...auditRange(form.fromDay, form.toDay) };
  for (const key of ['action', 'target_type', 'target_id', 'actor_role', 'request_id'] as const) {
    const value = form[key].trim();
    if (value) filters[key] = value;
  }
  return filters;
}

/** Append-only audit trail (Moderation spec 6.6): filter, page back in time with a stable cursor, inspect one event, export. */
export function Audit({ lang, role }: { lang: Lang; role: Role }) {
  const t = makeT(lang);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [applied, setApplied] = useState<AuditFilters>({});
  const [actions, setActions] = useState<string[]>([]);
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [open, setOpen] = useState<AuditItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuditActions()
      .then((answer) => setActions(answer.actions))
      .catch(() => undefined); // the free-text field still works without the list
  }, []);

  const load = useCallback(
    async (cursor?: string | null) => {
      try {
        const answer = await getAuditEvents(applied, cursor);
        setItems((current) => (cursor && current ? [...current, ...answer.items] : answer.items));
        setNext(answer.next_cursor);
        setError(null);
      } catch (failure) {
        setError(errorText(failure, lang));
      }
    },
    [applied, lang],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setOpen(null);
    setApplied(toFilters(form));
  };

  const download = async () => {
    setBusy(true);
    setNote(null);
    try {
      const result = await exportAuditCsv(applied);
      const url = URL.createObjectURL(new Blob([result.csv], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'audit-events.csv';
      link.click();
      URL.revokeObjectURL(url);
      setNote(result.truncated ? t(`প্রথম ${result.rows}টি ঘটনা নামানো হয়েছে; আরও আছে। ফিল্টার সংকীর্ণ করুন।`, `The first ${result.rows} events were exported; more match. Narrow the filter.`) : t(`${result.rows}টি ঘটনা নামানো হয়েছে।`, `${result.rows} events exported.`));
    } catch (failure) {
      setError(errorText(failure, lang));
    } finally {
      setBusy(false);
    }
  };

  const typeOptions = useMemo(() => ['review', 'task', 'report', 'user', 'enforcement_case', 'verification_case', 'appeal', 'destination', 'audit_log'], []);
  const field = (key: keyof FormState) => (value: string) => setForm({ ...form, [key]: value });

  return (
    <div className="queue-layout">
      <section className="card list-pane">
        <h2>{t('অডিট লগ', 'Audit log')}</h2>
        <form className="stack" onSubmit={submit}>
          <label htmlFor="f-action">{t('কাজ', 'Action')}</label>
          <input id="f-action" list="audit-actions" placeholder="report.create" value={form.action} onChange={(e) => field('action')(e.target.value)} />
          <datalist id="audit-actions">
            {actions.map((action) => (
              <option key={action} value={action} />
            ))}
          </datalist>
          <label htmlFor="f-type">{t('লক্ষ্যের ধরন', 'Target type')}</label>
          <select id="f-type" value={form.target_type} onChange={(e) => field('target_type')(e.target.value)}>
            <option value="">{t('সব', 'All')}</option>
            {typeOptions.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <label htmlFor="f-target">{t('লক্ষ্যের আইডি', 'Target id')}</label>
          <input id="f-target" value={form.target_id} onChange={(e) => field('target_id')(e.target.value.trim())} />
          <label htmlFor="f-role">{t('কর্তার ভূমিকা', 'Actor role')}</label>
          <select id="f-role" value={form.actor_role} onChange={(e) => field('actor_role')(e.target.value)}>
            <option value="">{t('সব', 'All')}</option>
            <option value="moderator">moderator</option>
            <option value="superadmin">superadmin</option>
          </select>
          <label htmlFor="f-request">{t('অনুরোধ আইডি', 'Request id')}</label>
          <input id="f-request" value={form.request_id} onChange={(e) => field('request_id')(e.target.value.trim())} />
          <div className="row">
            <div className="stack">
              <label htmlFor="f-from">{t('থেকে', 'From')}</label>
              <input id="f-from" type="date" value={form.fromDay} max={form.toDay || undefined} onChange={(e) => field('fromDay')(e.target.value)} />
            </div>
            <div className="stack">
              <label htmlFor="f-to">{t('পর্যন্ত', 'To')}</label>
              <input id="f-to" type="date" value={form.toDay} min={form.fromDay || undefined} onChange={(e) => field('toDay')(e.target.value)} />
            </div>
          </div>
          <div className="row">
            <button type="submit" className="primary">
              {t('ফিল্টার', 'Filter')}
            </button>
            <button type="button" className="ghost" onClick={() => { setForm(EMPTY); setApplied({}); setOpen(null); }}>
              {t('মুছুন', 'Clear')}
            </button>
            {isSuperadmin(role) && (
              <button type="button" className="ghost" disabled={busy} onClick={() => void download()}>
                {t('CSV নামান', 'Export CSV')}
              </button>
            )}
          </div>
        </form>
        {error && <Notice tone="error">{error}</Notice>}
        {note && <Notice tone="success">{note}</Notice>}
        {items?.length === 0 && <p className="muted">{t('কোনো ঘটনা নেই।', 'No events.')}</p>}
        <ul className="list">
          {items?.map((event) => (
            <li key={event.id}>
              <button type="button" className={`item ${open?.id === event.id ? 'selected' : ''}`} onClick={() => setOpen(event)}>
                <span className="item-title">{event.action}</span>
                <span className="small muted">
                  {new Date(event.occurred_at).toLocaleString(lang === 'bn' ? 'bn-BD' : 'en-GB')} · {event.actor_role ?? t('সিস্টেম', 'system')} · {event.target_type} {event.target_id.slice(0, 8)}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {next && (
          <button type="button" className="ghost" onClick={() => void load(next)}>
            {t('আরও পুরনো', 'Older')}
          </button>
        )}
      </section>
      <section className="card detail-pane">
        {!open && <p className="muted">{t('একটি ঘটনা বেছে নিন।', 'Pick an event.')}</p>}
        {open && (
          <dl className="facts">
            {(
              [
                ['id', open.id],
                [t('সময়', 'Time'), open.occurred_at],
                [t('কাজ', 'Action'), open.action],
                [t('কর্তা', 'Actor'), `${open.actor_user_id ?? t('সিস্টেম', 'system')} (${open.actor_role ?? '—'})`],
                [t('লক্ষ্য', 'Target'), `${open.target_type} ${open.target_id}`],
                [t('অনুরোধ আইডি', 'Request id'), open.request_id ?? '—'],
                [t('কারণ', 'Reason'), open.reason ?? '—'],
              ] as [string, string][]
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
            <div>
              <dt>{t('বিবরণ', 'Details')}</dt>
              <dd>
                <pre>{JSON.stringify(open.metadata, null, 2)}</pre>
              </dd>
            </div>
          </dl>
        )}
      </section>
    </div>
  );
}
