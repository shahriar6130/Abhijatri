import { useCallback, useEffect, useState } from 'react';
import { getInbox, markInboxAllRead, markInboxRead } from '../api';
import { errorText } from '../logic';
import type { InboxItem, Lang } from '../types';
import { Notice, makeT } from '../ui';

/**
 * The staff member's own notifications (Notification spec 3, moderator- and superadmin-facing events):
 * assignments, expiring claims, overdue queue, escalations and alerts. Staff notices disappear when
 * the role is revoked; the same inbox is also shown in the public app.
 */
export function Inbox({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const page = await getInbox();
      setItems(page.items);
      setCursor(page.next_cursor);
      setUnread(page.unread);
      setError(null);
    } catch (failure) {
      setError(errorText(failure, lang));
    }
  }, [lang]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000); // the inbox is the source of truth: poll it
    return () => window.clearInterval(timer);
  }, [load]);

  const more = async () => {
    if (!cursor) return;
    try {
      const page = await getInbox(cursor);
      setItems((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (failure) {
      setError(errorText(failure, lang));
    }
  };

  const read = async (item: InboxItem) => {
    if (item.read) return;
    try {
      await markInboxRead(item.id);
      setItems((current) => (current ?? []).map((n) => (n.id === item.id ? { ...n, read: true } : n)));
      setUnread((count) => Math.max(0, count - 1));
    } catch (failure) {
      setError(errorText(failure, lang));
    }
  };

  return (
    <section className="stack">
      <div className="row between">
        <h2>{t(`ইনবক্স (${unread} অপঠিত)`, `Inbox (${unread} unread)`)}</h2>
        <span className="row">
          <button type="button" className="ghost" onClick={() => void load()}>
            {t('হালনাগাদ', 'Refresh')}
          </button>
          {unread > 0 && (
            <button type="button" className="ghost" onClick={() => void markInboxAllRead().then(() => load())}>
              {t('সব পঠিত', 'Mark all read')}
            </button>
          )}
        </span>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {items === null && !error && <p className="muted">{t('লোড হচ্ছে…', 'Loading…')}</p>}
      {items !== null && items.length === 0 && <Notice tone="info">{t('কোনো বিজ্ঞপ্তি নেই।', 'No notifications.')}</Notice>}
      <ul className="stack">
        {items?.map((item) => (
          <li key={item.id} className="content-box">
            <div className="row between small">
              <span className="row">
                {!item.read && <span className="tag">{t('নতুন', 'new')}</span>}
                <span className="tag">{item.category}</span>
                {(item.priority === 'critical' || item.priority === 'high') && <span className="tag warn-text">{item.priority}</span>}
              </span>
              <span className="muted">{new Date(item.created_at).toLocaleString(lang === 'bn' ? 'bn-BD' : 'en-GB')}</span>
            </div>
            <strong>{lang === 'bn' ? item.title.bn : item.title.en}</strong>
            <span className="small">{lang === 'bn' ? item.body.bn : item.body.en}</span>
            {!item.read && (
              <button type="button" className="ghost small" onClick={() => void read(item)}>
                {t('পঠিত', 'Mark read')}
              </button>
            )}
          </li>
        ))}
      </ul>
      {cursor && (
        <button type="button" className="ghost" onClick={() => void more()}>
          {t('আরও', 'Load more')}
        </button>
      )}
    </section>
  );
}
