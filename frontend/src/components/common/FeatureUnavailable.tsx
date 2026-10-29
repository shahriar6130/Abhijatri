import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Clock, type LucideIcon } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';

type Pair = [bn: string, en: string];

/**
 * An honest placeholder for a feature whose backend or storage does not exist yet. It states what
 * the feature will do and what works today, and never shows invented data or calls a missing API
 * (QA_UI_UX 1 and 2; "no fake live claims").
 */
export const FeatureUnavailable: React.FC<{
  icon: LucideIcon;
  title: Pair;
  summary: Pair;
  /** What the finished feature will do. */
  plannedPoints: Pair[];
  /** Gantt task(s) that deliver it, e.g. "E08". Shown as a reference, not a promise date. */
  task: string;
  alternatives: { to: string; label: Pair }[];
}> = ({ icon: Icon, title, summary, plannedPoints, task, alternatives }) => {
  const { t } = useLanguage();

  return (
    <div className="flex flex-col gap-6 pb-12 max-w-3xl mx-auto">
      <div className="flex flex-col gap-2">
        <span className="self-start inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-100 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 text-xs font-bold">
          <Clock size={13} aria-hidden="true" />
          {t('এখনো চালু হয়নি', 'Not available yet')}
        </span>
        <h1 className="flex items-center gap-2 text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">
          <Icon size={26} className="text-forest-primary dark:text-neon-lime shrink-0" aria-hidden="true" />
          {t(...title)}
        </h1>
        <p className="text-sm sm:text-base font-body leading-relaxed text-on-surface-variant dark:text-on-dark-muted">{t(...summary)}</p>
      </div>

      <section aria-labelledby="planned-heading" className="tonal-card p-6 flex flex-col gap-3">
        <h2 id="planned-heading" className="text-base font-bold font-title text-on-surface dark:text-on-dark">
          {t('চালু হলে যা থাকবে', 'What it will do')}
        </h2>
        <ul className="flex flex-col gap-2 list-disc pl-5 text-sm text-on-surface dark:text-on-dark">
          {plannedPoints.map((point) => (
            <li key={point[1]}>{t(...point)}</li>
          ))}
        </ul>
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t('প্রকল্প কাজ', 'Project task')}: <span className="font-en">{task}</span>
        </p>
      </section>

      <section aria-labelledby="now-heading" className="flex flex-col gap-3">
        <h2 id="now-heading" className="text-sm font-bold text-on-surface-variant dark:text-on-dark-muted">
          {t('এখন যা করতে পারেন', 'What you can do now')}
        </h2>
        <ul className="flex flex-wrap gap-2">
          {alternatives.map(({ to, label }) => (
            <li key={to}>
              <Link
                to={to}
                className="inline-flex items-center gap-2 min-h-[44px] px-5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title"
              >
                {t(...label)}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
};
