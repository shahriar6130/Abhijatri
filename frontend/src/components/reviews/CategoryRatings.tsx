import React from 'react';
import { Star } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { REVIEW_CATEGORIES, cleanCategoryRatings, overallFromCategories } from '../../api/reviews';
import type { CategoryRatings as Ratings, ReviewCategory, ReviewParameters } from '../../types';
import { CATEGORY_LABEL } from './reviewLabels';
import { formatNumber } from '../../utils/format';

/**
 * The seven Review.md 3.1 category ratings, each 1 to 5. All seven are required, and the overall
 * rating is no longer asked: it is calculated from them and shown here (Decisions 2026-11-11,
 * amendment A6). Names and prompts come from the API's `/review-parameters` when available, with
 * the local labels as the offline fallback.
 */
export const CategoryRatings: React.FC<{
  value: Ratings;
  onChange: (next: Ratings) => void;
  pendingServerSupport: boolean;
  categories?: ReviewParameters['categories'];
  /** Shown under the list; its id is `errorId`, which the first unrated group points to. */
  error?: string;
  errorId?: string;
  /** Edit form: the ratings may be left as they are, and this says what changing them needs. */
  hint?: string;
}> = ({ value, onChange, pendingServerSupport, categories, error, errorId = 'category_ratings-error', hint }) => {
  const { language, t } = useLanguage();
  const rows = categories
    ? categories.map((c) => ({ code: c.code, name: c.name[language], prompt: c.prompt[language] }))
    : REVIEW_CATEGORIES.map((code) => ({
        code,
        name: t(...CATEGORY_LABEL[code].name),
        prompt: t(...CATEGORY_LABEL[code].prompt),
      }));

  const rated = cleanCategoryRatings(value);
  const ratedCount = Object.keys(rated).length;
  const overall = overallFromCategories(value);
  const average = ratedCount > 0 ? Object.values(rated).reduce((sum, v) => sum + (v ?? 0), 0) / ratedCount : null;
  const firstUnrated = rows.find((row) => rated[row.code] === undefined)?.code;
  const total = formatNumber(REVIEW_CATEGORIES.length, language);

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
        {t('বিষয়ভিত্তিক রেটিং (সবগুলো আবশ্যক)', 'Ratings by category (all required)')}
      </legend>
      <p className="text-xs text-on-surface-variant dark:text-on-dark-muted -mt-1">
        {hint ??
          t(
            `${total}টি বিষয়ের প্রতিটিতে ১ থেকে ৫ তারকা দিন। সার্বিক রেটিং এগুলো থেকে হিসাব করা হয়।`,
            `Give each of the ${total} categories 1 to 5 stars. The overall rating is calculated from them.`,
          )}
      </p>
      {pendingServerSupport && (
        <p className="text-xs p-2.5 rounded-lg bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          {t(
            'বিষয়ভিত্তিক রেটিং সার্ভারে এখনো সংরক্ষণ হয় না; রিভিউ সেবা হালনাগাদ হলে চালু হবে। এগুলো থেকে হিসাব করা সার্বিক রেটিং ও নোট এখনই জমা হবে।',
            'Category ratings are not stored by the server yet; they switch on when the review service is updated. The overall rating calculated from them and your note are submitted now.',
          )}
        </p>
      )}

      <ul className="flex flex-col divide-y divide-surface-muted/30 dark:divide-dark-surface-2">
        {rows.map(({ code: category, name, prompt }) => {
          const current = rated[category];
          return (
            <li key={category} className="py-2.5 flex flex-col sm:flex-row sm:items-center gap-2 sm:justify-between">
              <div className="flex flex-col">
                <span id={`cat-${category}`} className="text-sm font-semibold text-on-surface dark:text-on-dark">
                  {name}
                </span>
                <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">{prompt}</span>
              </div>
              <div
                role="radiogroup"
                aria-required="true"
                aria-labelledby={`cat-${category}`}
                aria-invalid={error && current === undefined ? true : undefined}
                aria-describedby={error && category === firstUnrated ? errorId : undefined}
                className="flex flex-wrap items-center gap-0.5 sm:shrink-0"
              >
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    role="radio"
                    aria-checked={current === star}
                    aria-label={t(`${name}: ${formatNumber(star, 'bn')} তারকা`, `${name}: ${star} star${star === 1 ? '' : 's'}`)}
                    onClick={() => onChange({ ...value, [category as ReviewCategory]: star })}
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full"
                  >
                    <Star
                      size={20}
                      aria-hidden="true"
                      className={current !== undefined && star <= current ? 'fill-foreground text-foreground' : 'text-surface-muted dark:text-on-dark-muted'}
                    />
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>

      {error && (
        <p id={errorId} className="text-xs text-error-alert dark:text-red-400">
          {error}
        </p>
      )}

      {/* The overall rating is an output now: read-only, and announced when it changes. */}
      <div
        role="status"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 rounded-xl bg-surface-container/60 dark:bg-dark-surface-2"
      >
        <span className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
          {t('সার্বিক রেটিং (হিসাব করা)', 'Overall rating (calculated)')}
        </span>
        {overall !== null && average !== null ? (
          <>
            <span className="inline-flex items-center gap-0.5" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((star) => (
                <Star key={star} size={18} className={star <= overall ? 'fill-foreground text-foreground' : 'text-surface-muted dark:text-on-dark-muted'} />
              ))}
            </span>
            <span className="text-sm font-semibold text-on-surface dark:text-on-dark">
              {t(
                `৫-এর মধ্যে ${formatNumber(overall, language)} (গড় ${formatNumber(average, language, 1)})`,
                `${overall} out of 5 (average ${formatNumber(average, language, 1)})`,
              )}
            </span>
          </>
        ) : (
          <span className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t(
              `${total}টির মধ্যে ${formatNumber(ratedCount, language)}টিতে রেটিং দেওয়া হয়েছে; সবগুলো দিলে দেখা যাবে।`,
              `${ratedCount} of ${REVIEW_CATEGORIES.length} rated; it appears when all are rated.`,
            )}
          </span>
        )}
      </div>
    </fieldset>
  );
};
