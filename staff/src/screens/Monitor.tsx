import { useCallback, useEffect, useState } from 'react';
import { getSummary } from '../api';
import { errorText } from '../logic';
import type { Lang, Summary } from '../types';
import { Notice, makeT } from '../ui';

function age(seconds: number | null, t: (bn: string, en: string) => string): string {
  if (seconds === null) return '—';
  if (seconds < 90) return t(`${seconds} সেকেন্ড`, `${seconds} s`);
  if (seconds < 5400) return t(`${Math.round(seconds / 60)} মিনিট`, `${Math.round(seconds / 60)} min`);
  return t(`${Math.round(seconds / 3600)} ঘণ্টা`, `${Math.round(seconds / 3600)} h`);
}

/** Moderation health at a glance (Moderation spec 12); the numbers come from the same database as the queue. */
export function Monitor({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSummary(await getSummary());
      setError(null);
    } catch (failure) {
      setError(errorText(failure, lang));
    }
  }, [lang]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const tiles: { label: string; value: string; level: 'ok' | 'warn' | 'critical' }[] = summary
    ? [
        { label: t('খোলা কাজ', 'Open tasks'), value: String(summary.queue_depth), level: summary.queue_depth > 50 ? 'warn' : 'ok' },
        { label: t('সবচেয়ে পুরনো কাজ', 'Oldest open task'), value: age(summary.oldest_open_task_age_seconds, t), level: (summary.oldest_open_task_age_seconds ?? 0) > 86400 ? 'critical' : (summary.oldest_open_task_age_seconds ?? 0) > 14400 ? 'warn' : 'ok' },
        { label: t('উপরে পাঠানো', 'Escalated'), value: String(summary.escalated_open), level: summary.escalated_open > 0 ? 'warn' : 'ok' },
        { label: t('মেয়াদোত্তীর্ণ লিজ', 'Expired claims'), value: String(summary.expired_claims), level: summary.expired_claims > 0 ? 'warn' : 'ok' },
        { label: t('খোলা রিপোর্ট', 'Open reports'), value: String(summary.open_reports), level: summary.open_reports > 20 ? 'warn' : 'ok' },
        { label: t('আউটবক্সে অপেক্ষমাণ', 'Outbox pending'), value: String(summary.outbox_pending), level: summary.outbox_pending > 500 ? 'critical' : summary.outbox_pending > 100 ? 'warn' : 'ok' },
        { label: t('খোলা যাচাই আবেদন', 'Open verification requests'), value: String(summary.open_verification_cases), level: 'ok' },
        { label: t('খোলা আপিল', 'Open appeals'), value: String(summary.open_appeals), level: summary.open_appeals > 10 ? 'warn' : 'ok' },
        { label: t('দেরি হওয়া জরুরি টেকডাউন', 'Overdue emergency takedowns'), value: String(summary.emergency_overdue), level: summary.emergency_overdue > 0 ? 'critical' : 'ok' },
        { label: t('সক্রিয় সীমাবদ্ধতা', 'Active restrictions'), value: String(summary.active_sanctions), level: 'ok' },
        { label: t('ব্যর্থ ইভেন্ট', 'Failed outbox events'), value: String(summary.outbox_failed), level: summary.outbox_failed > 0 ? 'critical' : 'ok' },
        { label: t('সবচেয়ে পুরনো অপেক্ষমাণ ইভেন্ট', 'Oldest pending event'), value: age(summary.oldest_pending_event_age_seconds, t), level: (summary.oldest_pending_event_age_seconds ?? 0) > 300 ? 'warn' : 'ok' },
        { label: t('ব্যর্থ বা অনিশ্চিত ইমেইল', 'Failed or unclear emails'), value: String(summary.emails_failed_or_ambiguous), level: summary.emails_failed_or_ambiguous > 0 ? 'warn' : 'ok' },
        { label: t('২৪ ঘণ্টায় প্রত্যাখ্যাত চেষ্টা', 'Denied attempts, 24 h'), value: String(summary.denied_last_24h), level: summary.denied_last_24h > 10 ? 'warn' : 'ok' },
      ]
    : [];

  return (
    <div className="stack">
      {error && <Notice tone="error">{error}</Notice>}
      <div className="stats">
        {tiles.map((tile) => (
          <div key={tile.label} className={`stat level-${tile.level}`}>
            <span className="stat-label">{tile.label}</span>
            <span className="stat-value">{tile.value}</span>
          </div>
        ))}
      </div>
      {summary && <p className="muted small">{t('হালনাগাদ', 'Updated')}: {new Date(summary.generated_at).toLocaleTimeString()}</p>}
    </div>
  );
}
