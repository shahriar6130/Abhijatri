import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { getAuditEvents } from '../api';
import { errorText } from '../logic';
import type { AuditItem, Lang } from '../types';
import { Notice, makeT } from '../ui';

/** Append-only audit trail (Moderation spec 6.6): filter, page back in time, inspect one event. */
export function Audit({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [filters, setFilters] = useState({ action: '', target_type: '', target_id: '' });
  const [applied, setApplied] = useState(filters);
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [open, setOpen] = useState<AuditItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (before?: string) => {
      try {
        const answer = await getAuditEvents({ ...applied, before });
        setItems((current) => (before && current ? [...current, ...answer.items] : answer.items));
        setNext(answer.next_before);
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
    setApplied(filters);
  };

  return (
    <div className="queue-layout">
      <section className="card list-pane">
        <h2>{t('অডিট লগ', 'Audit log')}</h2>
        <form className="stack" onSubmit={submit}>
          <label htmlFor="f-action">{t('কাজ', 'Action')}</label>
          <input id="f-action" placeholder="review.publish" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} />
          <label htmlFor="f-type">{t('লক্ষ্যের ধরন', 'Target type')}</label>
          <select id="f-type" value={filters.target_type} onChange={(e) => setFilters({ ...filters, target_type: e.target.value })}>
            <option value="">{t('সব', 'All')}</option>
            {['review', 'task', 'report', 'user'].map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <label htmlFor="f-target">{t('লক্ষ্যের আইডি', 'Target id')}</label>
          <input id="f-target" value={filters.target_id} onChange={(e) => setFilters({ ...filters, target_id: e.target.value.trim() })} />
          <button type="submit" className="primary">
            {t('ফিল্টার', 'Filter')}
          </button>
        </form>
        {error && <Notice tone="error">{error}</Notice>}
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
