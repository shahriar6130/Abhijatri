import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { REPORT_REASONS, getMyReports, type MyReport } from '../api/reports';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { linkClass } from '../components/auth/AccountUi';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { formatTimestamp, pick } from '../utils/format';

const STATE_LABEL: Record<MyReport['state'], { bn: string; en: string }> = {
  open: { bn: 'জমা হয়েছে', en: 'Received' },
  in_review: { bn: 'পর্যালোচনা চলছে', en: 'Being reviewed' },
  actioned: { bn: 'ব্যবস্থা নেওয়া হয়েছে', en: 'Action taken' },
  dismissed: { bn: 'ব্যবস্থার প্রয়োজন হয়নি', en: 'No action needed' },
};

/** The member's own reports and where each stands. It never shows who handled them or what staff wrote. */
export const MyReportsPage: React.FC = () => {
  const { t, language } = useLanguage();
  const { session, status } = useSession();
  const [items, setItems] = useState<MyReport[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async (after?: string | null) => {
    try {
      const page = await getMyReports(after);
      setItems((current) => (after ? [...current, ...page.items] : page.items));
      setCursor(page.next_cursor);
      setError(null);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (session.kind === 'member') void load();
    else setLoading(false);
  }, [session.kind, load]);

  if (status === 'loading') return <LoadingState />;
  if (session.kind !== 'member') {
    return (
      <EmptyState
        title={t('রিপোর্ট দেখতে সাইন ইন করুন', 'Sign in to see your reports')}
        action={
          <Link to="/login" className={linkClass}>
            {t('সাইন ইন', 'Sign in')}
          </Link>
        }
      />
    );
  }
  if (loading) return <LoadingState />;
  if (error !== null) return <ErrorState error={error} onRetry={() => void load()} />;

  const reasonLabel = (code: string) => {
    const found = REPORT_REASONS.find((r) => r.value === code);
    return found ? pick(language, found.bn, found.en) : code;
  };

  return (
    <div className="flex flex-col gap-4 pb-12 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('আমার রিপোর্ট', 'My reports')}</h1>
      {items.length === 0 ? (
        <EmptyState title={t('আপনি এখনো কোনো রিপোর্ট পাঠাননি', 'You have not sent any reports')} />
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((report) => (
            <li key={report.id} className="tonal-card p-4 flex flex-col gap-1">
              <span className="text-sm font-bold">{reasonLabel(report.reason_code)}</span>
              <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">
                {pick(language, STATE_LABEL[report.state].bn, STATE_LABEL[report.state].en)} · {formatTimestamp(report.created_at, language)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {cursor && (
        <button type="button" onClick={() => void load(cursor)} className="self-start min-h-[44px] px-5 rounded-full border border-surface-muted dark:border-dark-surface-2 font-bold">
          {t('আরও দেখান', 'Show more')}
        </button>
      )}
    </div>
  );
};
