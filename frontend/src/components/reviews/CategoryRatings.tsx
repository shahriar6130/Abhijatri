import React from 'react';
import { Star } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { REVIEW_CATEGORIES } from '../../api/reviews';
import type { CategoryRatings as Ratings, ReviewCategory, ReviewParameters } from '../../types';
import { CATEGORY_LABEL } from './reviewLabels';

/**
 * The seven Review.md 3.1 category ratings, each 1 to 5 or "not applicable". Optional: the
 * overall rating stays the single required score. Names and prompts come from the API's
 * `/review-parameters` when available, with the local labels as the offline fallback.
 */
export const CategoryRatings: React.FC<{
  value: Ratings;
  onChange: (next: Ratings) => void;
  pendingServerSupport: boolean;
  categories?: ReviewParameters['categories'];
}> = ({ value, onChange, pendingServerSupport, categories }) => {
  const { language, t } = useLanguage();
  const rows = categories
    ? categories.map((c) => ({ code: c.code, name: c.name[language], prompt: c.prompt[language] }))
    : REVIEW_CATEGORIES.map((code) => ({
        code,
        name: t(...CATEGORY_LABEL[code].name),
        prompt: t(...CATEGORY_LABEL[code].prompt),
      }));

  const set = (category: ReviewCategory, rating: number | undefined) => {
    const next = { ...value };
    if (rating === undefined) delete next[category];
    else next[category] = rating;
    onChange(next);
  };

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
        {t('বিষয়ভিত্তিক রেটিং (ঐচ্ছিক)', 'Ratings by category (optional)')}
      </legend>
      <p className="text-xs text-on-surface-variant dark:text-on-dark-muted -mt-1">
        {t(
          'যেটি প্রযোজ্য নয় বা জানেন না, সেটি "প্রযোজ্য নয়" রাখুন।',
          'Leave anything you did not experience as "Not applicable".',
        )}
      </p>
      {pendingServerSupport && (
        <p className="text-xs p-2.5 rounded-lg bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {t(
            'বিষয়ভিত্তিক রেটিং সার্ভারে এখনো সংরক্ষণ হয় না; রিভিউ সেবা হালনাগাদ হলে চালু হবে। সার্বিক রেটিং ও নোট এখনই জমা হবে।',
            'Category ratings are not stored by the server yet; they switch on when the review service is updated. Your overall rating and note are submitted now.',
          )}
        </p>
      )}

      <ul className="flex flex-col divide-y divide-surface-muted/30 dark:divide-dark-surface-2">
        {rows.map(({ code: category, name, prompt }) => {
          const current = value[category];
          return (
            <li key={category} className="py-2.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:justify-between">
              <div className="flex flex-col">
                <span id={`cat-${category}`} className="text-sm font-semibold text-on-surface dark:text-on-dark">
                  {name}
                </span>
                <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">{prompt}</span>
              </div>
              <div role="radiogroup" aria-labelledby={`cat-${category}`} className="flex flex-wrap items-center gap-0.5 sm:shrink-0">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    role="radio"
                    aria-checked={current === star}
                    aria-label={t(`${name}: ${star} তারকা`, `${name}: ${star} star${star === 1 ? '' : 's'}`)}
                    onClick={() => set(category, star)}
                    className="min-w-[40px] min-h-[40px] flex items-center justify-center rounded-full"
                  >
                    <Star
                      size={20}
                      aria-hidden="true"
                      className={current !== undefined && star <= current ? 'fill-amber-400 text-amber-400' : 'text-surface-muted dark:text-on-dark-muted'}
                    />
                  </button>
                ))}
                <button
                  type="button"
                  role="radio"
                  aria-checked={current === undefined}
                  onClick={() => set(category, undefined)}
                  className={`ml-1 min-h-[40px] px-3 rounded-full text-[11px] font-semibold ${
                    current === undefined
                      ? 'bg-surface-container dark:bg-dark-surface-2 text-on-surface dark:text-on-dark'
                      : 'text-on-surface-variant dark:text-on-dark-muted'
                  }`}
                >
                  {t('প্রযোজ্য নয়', 'Not applicable')}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
};
