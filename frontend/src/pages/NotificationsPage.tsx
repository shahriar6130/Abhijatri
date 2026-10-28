import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Archive, ArchiveRestore, BellRing, Check, Mail } from 'lucide-react';
import {
  getNotificationPreferences,
  getNotifications,
  markAllRead,
  saveNotificationPreferences,
  updateNotification,
} from '../api/account';
import { Notice, accountErrorMessage, inputClass, linkClass, primaryButtonClass } from '../components/auth/AccountUi';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { STAFF_BASE_URL } from '../components/layout/NotificationBell';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { AppNotification, NotificationPreferences } from '../types';
import { formatTimestamp } from '../utils/format';
import { CATEGORY_LABEL, categoryOf, linkTarget } from '../utils/notifications';

type View = 'all' | 'unread' | 'archived';

const PRIORITY_TEXT: Record<string, [string, string]> = {
  critical: ['গুরুত্বপূর্ণ', 'Important'],
  high: ['জরুরি', 'Urgent'],
};

/** The full inbox and email preferences (Notification spec 9 and 12). */
export const NotificationsPage: React.FC = () => {
  const { t, language } = useLanguage();
  const { session, status } = useSession();
  const [view, setView] = useState<View>('all');
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [saving, setSaving] = useState(false);
  const lang = language === 'bn' ? 'bn' : 'en';

  const load = useCallback(async () => {
    setError(null);
    setItems(null);
    try {
      const page = await getNotifications({ archived: view === 'archived', unreadOnly: view === 'unread' });
      setItems(page.items);
      setCursor(page.next_cursor);
      setUnread(page.unread);
    } catch (failure) {
      setError(failure);
    }
  }, [view]);

  useEffect(() => {
    if (session.kind !== 'member') return;
    void load();
  }, [session.kind, load]);

  useEffect(() => {
    if (session.kind !== 'member') return;
    getNotificationPreferences().then(setPrefs).catch(() => undefined);
  }, [session.kind]);

  if (status === 'loading') return <LoadingState />; // the session is still being read; do not ask to sign in yet

  if (session.kind !== 'member') {
    return (
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-10">
        <Notice tone="info">
          {t('বিজ্ঞপ্তি দেখতে সাইন ইন করুন।', 'Sign in to see your notifications.')}{' '}
          <Link to="/login" className={linkClass}>
            {t('সাইন ইন', 'Sign in')}
          </Link>
        </Notice>
      </div>
    );
  }

  const more = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await getNotifications({ cursor, archived: view === 'archived', unreadOnly: view === 'unread' });
      setItems((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (failure) {
      setMessage({ tone: 'error', text: accountErrorMessage(failure, t) });
    } finally {
      setLoadingMore(false);
    }
  };

  const change = async (item: AppNotification, patch: { read?: boolean; archived?: boolean }) => {
    try {
      const answer = await updateNotification(item.id, patch);
      setUnread(answer.unread);
      setItems((current) => {
        const next = (current ?? []).map((n) => (n.id === item.id ? { ...n, read: answer.read, archived: answer.archived } : n));
        // An archived item leaves the normal list, and an unarchived one leaves the archive.
        return patch.archived === undefined ? next : next.filter((n) => n.id !== item.id);
      });
    } catch (failure) {
      setMessage({ tone: 'error', text: accountErrorMessage(failure, t) });
    }
  };

  const savePrefs = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!prefs) return;
    setSaving(true);
    setMessage(null);
    try {
      setPrefs(await saveNotificationPreferences(prefs));
      setMessage({ tone: 'success', text: t('ইমেইল সেটিংস সংরক্ষিত হয়েছে।', 'Email settings saved.') });
    } catch (failure) {
      setMessage({ tone: 'error', text: accountErrorMessage(failure, t) });
    } finally {
      setSaving(false);
    }
  };

  const tabs: [View, string][] = [
    ['all', t('সব', 'All')],
    ['unread', t(`অপঠিত (${unread})`, `Unread (${unread})`)],
    ['archived', t('আর্কাইভ', 'Archived')],
  ];

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark flex items-center gap-2">
          <BellRing size={24} aria-hidden="true" className="text-forest-primary dark:text-neon-lime" />
          {t('বিজ্ঞপ্তি', 'Notifications')}
        </h1>
        {unread > 0 && view !== 'archived' && (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs font-bold text-forest-primary dark:text-neon-lime"
            onClick={() => void markAllRead().then(() => { setUnread(0); setItems((c) => (c ?? []).map((n) => ({ ...n, read: true }))); })}
          >
            <Check size={14} aria-hidden="true" />
            {t('সব পঠিত চিহ্নিত করুন', 'Mark all read')}
          </button>
        )}
      </div>

      {message && <Notice tone={message.tone}>{message.text}</Notice>}

      <div role="tablist" className="flex gap-2">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id)}
            className={`min-h-[40px] px-4 rounded-full text-xs font-bold font-title ${
              view === id ? 'bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base' : 'bg-surface-sage dark:bg-dark-surface-2 text-on-surface dark:text-on-dark'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {items === null && !error && <LoadingState label={t('বিজ্ঞপ্তি লোড হচ্ছে…', 'Loading notifications…')} />}
      {error !== null && <ErrorState error={error} onRetry={() => void load()} />}
      {items !== null && items.length === 0 && (
        <EmptyState
          title={view === 'archived' ? t('আর্কাইভ খালি', 'The archive is empty') : t('কোনো বিজ্ঞপ্তি নেই', 'No notifications')}
          hint={t('রিভিউ, যাচাই ও আপিলের সিদ্ধান্ত এখানে আসবে।', 'Decisions about your reviews, verification and appeals appear here.')}
        />
      )}

      {items !== null && items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.map((item) => {
            const target = linkTarget(item.link, STAFF_BASE_URL);
            const category = CATEGORY_LABEL[categoryOf(item)];
            const priority = item.priority ? PRIORITY_TEXT[item.priority] : undefined;
            return (
              <li key={item.id} className={`tonal-card p-4 flex flex-col gap-2 ${item.read ? 'opacity-80' : ''}`}>
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-on-surface-variant dark:text-on-dark-muted">
                  {!item.read && <span className="w-2 h-2 rounded-full bg-forest-primary dark:bg-neon-lime" aria-label={t('অপঠিত', 'unread')} />}
                  {category && <span className="px-2 py-0.5 rounded-full bg-surface-sage dark:bg-dark-surface-2 font-bold">{t(...category)}</span>}
                  {priority && <span className="px-2 py-0.5 rounded-full bg-error-container text-red-900 dark:bg-red-950/40 dark:text-red-200 font-bold">{t(...priority)}</span>}
                  <span className="ml-auto">{formatTimestamp(item.created_at, language)}</span>
                </div>
                <p className="text-sm font-bold text-on-surface dark:text-on-dark">{item.title[lang]}</p>
                <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{item.body[lang]}</p>
                <div className="flex flex-wrap gap-4 text-xs">
                  {target && 'internal' in target && (
                    <Link to={target.internal} onClick={() => void change(item, { read: true })} className={linkClass}>
                      {t('দেখুন', 'Open')}
                    </Link>
                  )}
                  {target && 'external' in target && (
                    <a href={target.external} target="_blank" rel="noopener noreferrer" className={linkClass}>
                      {t('কর্মী ড্যাশবোর্ডে খুলুন', 'Open in the staff dashboard')}
                    </a>
                  )}
                  <button type="button" className={linkClass} onClick={() => void change(item, { read: !item.read })}>
                    {item.read ? t('অপঠিত করুন', 'Mark unread') : t('পঠিত করুন', 'Mark read')}
                  </button>
                  <button type="button" className={`${linkClass} inline-flex items-center gap-1`} onClick={() => void change(item, { archived: !item.archived })}>
                    {item.archived ? <ArchiveRestore size={12} aria-hidden="true" /> : <Archive size={12} aria-hidden="true" />}
                    {item.archived ? t('আর্কাইভ থেকে ফেরান', 'Unarchive') : t('আর্কাইভ', 'Archive')}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {cursor && (
        <button type="button" onClick={() => void more()} disabled={loadingMore} className="self-center text-xs font-bold text-forest-primary dark:text-neon-lime">
          {loadingMore ? t('লোড হচ্ছে…', 'Loading…') : t('আরও দেখুন', 'Load more')}
        </button>
      )}

      <form onSubmit={(event) => void savePrefs(event)} className="tonal-card p-5 flex flex-col gap-4">
        <h2 className="text-lg font-bold font-title text-on-surface dark:text-on-dark flex items-center gap-2">
          <Mail size={18} aria-hidden="true" />
          {t('ইমেইল', 'Email')}
        </h2>
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t(
            'গুরুত্বপূর্ণ ও জরুরি বিজ্ঞপ্তি (যেমন রিভিউ বাতিল, আপিলের সিদ্ধান্ত, অ্যাকাউন্টের ব্যবস্থা) সবসময় সাথে সাথে ইমেইলে যায়। নিচের সেটিং বাকিগুলোর জন্য।',
            'Important and urgent notices (a rejected review, an appeal decision, an account action) are always emailed at once. The setting below is for the rest.',
          )}
        </p>
        {prefs === null ? (
          <LoadingState />
        ) : (
          <>
            <fieldset className="flex flex-col gap-2 text-sm text-on-surface dark:text-on-dark">
              {(
                [
                  ['immediate', t('সাথে সাথে', 'At once')],
                  ['digest', t('দিনে একবার সারসংক্ষেপ', 'A daily summary')],
                  ['off', t('ইমেইল নয় (শুধু এখানে)', 'No email (only here)')],
                ] as [NotificationPreferences['standard_email_mode'], string][]
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 min-h-[36px]">
                  <input
                    type="radio"
                    name="email-mode"
                    checked={prefs.standard_email_mode === value}
                    onChange={() => setPrefs({ ...prefs, standard_email_mode: value })}
                    className="accent-forest-primary dark:accent-neon-lime"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            {prefs.standard_email_mode === 'digest' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="flex flex-col gap-1 text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
                  {t('সারসংক্ষেপের সময়', 'Summary time')}
                  <input
                    type="time"
                    value={prefs.digest_local_time}
                    onChange={(e) => setPrefs({ ...prefs, digest_local_time: e.target.value })}
                    className={inputClass}
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
                  {t('সময় অঞ্চল', 'Time zone')}
                  <input
                    value={prefs.digest_timezone}
                    onChange={(e) => setPrefs({ ...prefs, digest_timezone: e.target.value })}
                    placeholder="Asia/Dhaka"
                    className={inputClass}
                  />
                </label>
              </div>
            )}
            <button type="submit" disabled={saving} className={`${primaryButtonClass} self-start`}>
              {saving ? t('সংরক্ষণ হচ্ছে…', 'Saving…') : t('সংরক্ষণ করুন', 'Save')}
            </button>
          </>
        )}
      </form>
    </div>
  );
};
