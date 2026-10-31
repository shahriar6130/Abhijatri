import React from 'react';
import { ShieldCheck, Star, Users } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import type { RatingSummary as Rating } from '../../types';
import { formatNumber } from '../../utils/format';

/** Review.md 6.4: Community Rating is not shown until five eligible Verified Member reviews exist. */
export const COMMUNITY_RATING_THRESHOLD = 5;

/** Review.md 6.1: fixed semester prior C = 3.5, confidence weight m = 5. */
const PRIOR_MEAN = 3.5;
const PRIOR_WEIGHT = 5;

/** "1 of 5 verified reviews": how many eligible reviews exist toward the threshold of Review.md 6.4. */
export function seededProgress(count: number): string {
  return `${Math.min(count, COMMUNITY_RATING_THRESHOLD)} of ${COMMUNITY_RATING_THRESHOLD} verified reviews`;
}

export function bayesianScore(rating: Rating): number | null {
  if (rating.average === null || rating.count === 0) return null;
  return (rating.average * rating.count + PRIOR_WEIGHT * PRIOR_MEAN) / (rating.count + PRIOR_WEIGHT);
}

/**
 * Community Rating and Guest Feedback are separate claims (Review.md 6.1, 6.2) and are never
 * merged. Every value is shown with its count.
 */
export const RatingSummary: React.FC<{ community: Rating; guest: Rating; compact?: boolean }> = ({
  community,
  guest,
  compact = false,
}) => {
  const { language, t } = useLanguage();
  // The API computes the score (API.md 5.12); the local formula covers older API builds only.
  const score =
    community.score !== undefined
      ? community.score
      : community.count >= COMMUNITY_RATING_THRESHOLD
        ? bayesianScore(community)
        : null;
  const pill = 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold';

  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? '' : 'text-xs'}`}>
      {score !== null ? (
        <span className={`${pill} bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-emerald-accent`}>
          <ShieldCheck size={13} aria-hidden="true" />
          {t('কমিউনিটি রেটিং', 'Community Rating')} {formatNumber(score, language, 1)}
          <span className="opacity-75">
            {t(
              `(${formatNumber(community.count, language)}টি যাচাইকৃত রিভিউ)`,
              `(${community.count} verified review${community.count === 1 ? '' : 's'})`,
            )}
          </span>
        </span>
      ) : (
        <span
          className={`${pill} bg-surface-container/70 dark:bg-dark-surface-2 text-on-surface-variant dark:text-on-dark-muted`}
          title={t(
            'পাঁচটি যাচাইকৃত সদস্য রিভিউয়ের আগে কমিউনিটি রেটিং দেখানো হয় না।',
            'Community Rating appears after five Verified Member reviews.',
          )}
        >
          <ShieldCheck size={13} aria-hidden="true" />
          {/* Review.md 6.4 term; it is editorial, not a community ranking. */}
          {t('সম্পাদকীয় গন্তব্য নির্বাচন', 'Seeded Destination Selection')}
          {/* The count is always shown (Review.md 6.1), so a reader sees how far the destination is from a rating. */}
          <span className="opacity-75">
            {t(
              `(${formatNumber(Math.min(community.count, COMMUNITY_RATING_THRESHOLD), language)}/${formatNumber(COMMUNITY_RATING_THRESHOLD, language)}টি যাচাইকৃত রিভিউ)`,
              `(${seededProgress(community.count)})`,
            )}
          </span>
        </span>
      )}

      <span className={`${pill} bg-surface-container/70 dark:bg-dark-surface-2 text-on-surface-variant dark:text-on-dark-muted`}>
        <Users size={13} aria-hidden="true" />
        {t('অতিথি মতামত', 'Guest Feedback')}{' '}
        {guest.average !== null && guest.count > 0 ? (
          <>
            <Star size={12} className="fill-amber-400 text-amber-400" aria-hidden="true" />
            {formatNumber(guest.average, language, 1)}
            <span className="opacity-75">
              {t(
                `(${formatNumber(guest.count, language)}টি রিভিউ)`,
                `(${guest.count} review${guest.count === 1 ? '' : 's'})`,
              )}
            </span>
          </>
        ) : (
          <span className="opacity-75">{t('এখনো নেই', 'none yet')}</span>
        )}
      </span>
    </div>
  );
};
