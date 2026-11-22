import React from 'react';
import { useLanguage } from '../../context/LanguageContext';
import type { CategoryAverage, CategoryRatings } from '../../types';
import { CATEGORY_LABEL } from '../reviews/reviewLabels';
import { formatNumber } from '../../utils/format';

/**
 * Per-category averages (API.md 5.8, 5.12). The API lists only categories that have a counted
 * rating, already in Review.md order; each value is shown with its own count. Renders nothing
 * when there is nothing to show.
 */
export const CategoryAverages: React.FC<{ averages?: CategoryAverage[]; title: string }> = ({ averages, title }) => {
  const { language, t } = useLanguage();
  if (!averages || averages.length === 0) return null;

  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <h3 className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">{title}</h3>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
        {averages.map(({ category, average, count }) => (
          <li key={category} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="font-semibold text-on-surface dark:text-on-dark">{t(...CATEGORY_LABEL[category].name)}</span>
              <span className="text-on-surface-variant dark:text-on-dark-muted">
                {formatNumber(average, language, 1)} / {formatNumber(5, language)} ({formatNumber(count, language)})
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-surface-container dark:bg-dark-surface-2 overflow-hidden" aria-hidden="true">
              <div className="h-full rounded-full bg-foreground" style={{ width: `${(average / 5) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
};

/** One review's own category scores as compact chips ("Food 4★"). */
export const CategoryChips: React.FC<{ ratings?: CategoryRatings }> = ({ ratings }) => {
  const { language, t } = useLanguage();
  const entries = Object.entries(ratings ?? {}) as [keyof typeof CATEGORY_LABEL, number][];
  if (entries.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={t('বিষয়ভিত্তিক রেটিং', 'Ratings by category')}>
      {entries.map(([category, score]) => (
        <li
          key={category}
          className="px-2 py-0.5 rounded-full bg-surface-container dark:bg-dark-surface-2 text-[11px] font-semibold text-on-surface-variant dark:text-on-dark-muted"
        >
          {t(...CATEGORY_LABEL[category].name)} {formatNumber(score, language)}★
        </li>
      ))}
    </ul>
  );
};
