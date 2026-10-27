import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell } from 'lucide-react';
import { getNotifications, markAllRead, markRead, subscribeToNotifications } from '../../api/account';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import type { AppNotification } from '../../types';
import { formatTimestamp } from '../../utils/format';

/**
 * In-app notifications for signed-in members (Moderation spec 11). New items arrive live over
 * Server-Sent Events; a decision made by staff shows here within a few seconds.
 */
export const NotificationBell: React.FC = () => {
  const { t, language } = useLanguage();
  const { session, refresh } = useSession();
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [flash, setFlash] = useState<AppNotification | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const member = session.kind === 'member';

  useEffect(() => {
    if (!member) return undefined;
    getNotifications()
      .then((answer) => {
        setItems(answer.items);
        setUnread(answer.unread);
      })
      .catch(() => undefined);
    return subscribeToNotifications(setUnread, (item, count) => {
      setItems((current) => [item, ...current.filter((existing) => existing.id !== item.id)].slice(0, 20));
      setUnread(count);
      setFlash(item);
      if (item.kind.startsWith('verification.')) void refresh(); // the Verified Member badge may have changed
    });
  }, [member, refresh]);

  useEffect(() => {
    if (!flash) return undefined;
    const timer = window.setTimeout(() => setFlash(null), 6000);
    return () => window.clearTimeout(timer);
  }, [flash]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event: MouseEvent) => {
      if (panel.current && !panel.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const read = useCallback(async (item: AppNotification) => {
    if (item.read) return;
    const answer = await markRead(item.id).catch(() => null);
    if (answer) {
      setUnread(answer.unread);
      setItems((current) => current.map((n) => (n.id === item.id ? { ...n, read: true } : n)));
    }
  }, []);

  if (!member) return null;

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={t(`বিজ্ঞপ্তি, ${unread} টি অপঠিত`, `Notifications, ${unread} unread`)}
        className="relative p-2 rounded-xl text-on-surface dark:text-on-dark hover:bg-surface-sage dark:hover:bg-dark-surface-1"
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-error-alert text-white text-[10px] font-bold leading-[18px] text-center">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {flash && !open && (
        <div role="status" className="absolute right-0 top-12 w-72 p-3 rounded-xl shadow-lg bg-white dark:bg-dark-surface-1 border border-surface-muted/40 dark:border-dark-surface-2 text-xs">
          <p className="font-bold text-on-surface dark:text-on-dark">{flash.title[language === 'bn' ? 'bn' : 'en']}</p>
          <p className="text-on-surface-variant dark:text-on-dark-muted">{flash.body[language === 'bn' ? 'bn' : 'en']}</p>
        </div>
      )}

      {open && (
        <div className="absolute right-0 top-12 w-80 max-h-[70vh] overflow-auto rounded-xl shadow-lg bg-white dark:bg-dark-surface-1 border border-surface-muted/40 dark:border-dark-surface-2 z-40">
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-muted/30 dark:border-dark-surface-2">
            <span className="text-sm font-bold font-title text-on-surface dark:text-on-dark">{t('বিজ্ঞপ্তি', 'Notifications')}</span>
            {unread > 0 && (
              <button
                type="button"
                className="text-xs font-bold text-forest-primary dark:text-neon-lime"
                onClick={() => void markAllRead().then(() => { setUnread(0); setItems((c) => c.map((n) => ({ ...n, read: true }))); })}
              >
                {t('সব পঠিত', 'Mark all read')}
              </button>
            )}
          </div>
          {items.length === 0 && <p className="px-4 py-6 text-xs text-on-surface-variant dark:text-on-dark-muted">{t('এখনো কোনো বিজ্ঞপ্তি নেই।', 'No notifications yet.')}</p>}
          <ul>
            {items.map((item) => {
              const lang = language === 'bn' ? 'bn' : 'en';
              const content = (
                <>
                  <span className="flex items-center gap-2">
                    {!item.read && <span className="w-2 h-2 rounded-full bg-forest-primary dark:bg-neon-lime shrink-0" aria-label={t('অপঠিত', 'unread')} />}
                    <span className="font-bold text-on-surface dark:text-on-dark">{item.title[lang]}</span>
                  </span>
                  <span className="block text-on-surface-variant dark:text-on-dark-muted">{item.body[lang]}</span>
                  <span className="block text-[10px] text-on-surface-variant/70 dark:text-on-dark-muted mt-1">{formatTimestamp(item.created_at, language)}</span>
                </>
              );
              return (
                <li key={item.id} className="border-b border-surface-muted/20 dark:border-dark-surface-2 last:border-0">
                  {item.link ? (
                    <Link to={item.link} onClick={() => { void read(item); setOpen(false); }} className="block px-4 py-3 text-xs hover:bg-surface-sage/40 dark:hover:bg-dark-surface-2">
                      {content}
                    </Link>
                  ) : (
                    <button type="button" onClick={() => void read(item)} className="block w-full text-left px-4 py-3 text-xs hover:bg-surface-sage/40 dark:hover:bg-dark-surface-2">
                      {content}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
};
