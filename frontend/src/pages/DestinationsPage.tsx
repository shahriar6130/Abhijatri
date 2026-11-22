import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ArrowUpDown, MapPin, Search } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { useDestinationCatalog } from '../hooks/useDestinationCatalog';
import { EmptyState, ErrorState, LoadingState, OfflineEmptyState, OfflineSavedNotice } from '../components/common/StatusViews';
import { RatingSummary } from '../components/destination/RatingSummary';
import { sortDestinations, type DestinationSort } from '../utils/destinationSort';
import { formatNumber, pick } from '../utils/format';

export const DestinationsPage: React.FC = () => {
  const { language, t } = useLanguage();
  // The front page's search arrives as `?q=` (UI refresh, 22 Nov 2026).
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '');
  const [sort, setSort] = useState<DestinationSort>('name');
  const { data: catalog, error, loading, reload } = useDestinationCatalog();
  const data = catalog?.items ?? null;
  const savedOnly = catalog?.saved ?? false;

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const found =
      !data || !needle
        ? (data ?? [])
        : data.filter((d) => [d.name_bn, d.name_en, d.region_bn, d.region_en].some((v) => v?.toLocaleLowerCase().includes(needle)));
    return sortDestinations(found, sort);
  }, [data, query, sort]);

  return (
    <div className="flex flex-col gap-6 pb-12">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark tracking-tight">
            {t('গন্তব্য ও ভ্রমণ গাইড', 'Destinations & Guides')}
          </h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted font-body mt-1">
            {t(
              'সূত্র ও তারিখসহ দ্বিভাষিক তথ্য, নিরাপত্তা সতর্কতা ও জরুরি যোগাযোগ।',
              'Bilingual, source-dated guidance with safety advisories and emergency contacts.',
            )}
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 w-full md:w-auto">
          <label className="relative w-full sm:w-72">
            <span className="sr-only">{t('গন্তব্য খুঁজুন', 'Filter destinations')}</span>
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant" size={16} aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('নাম বা এলাকা দিয়ে খুঁজুন', 'Filter by name or region')}
              className="w-full pl-10 pr-4 min-h-[44px] rounded-full bg-surface-sage/50 dark:bg-dark-surface-1 border border-surface-muted/40 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark"
            />
          </label>
          <label className="relative w-full sm:w-52">
            <span className="sr-only">{t('সাজানোর ক্রম', 'Sort order')}</span>
            <ArrowUpDown className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant pointer-events-none" size={16} aria-hidden="true" />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as DestinationSort)}
              className="w-full pl-10 pr-4 min-h-[44px] rounded-full bg-surface-sage/50 dark:bg-dark-surface-1 border border-surface-muted/40 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark"
            >
              <option value="name">{t('নাম অনুযায়ী', 'By name')}</option>
              <option value="best">{t('সেরা রেটিং আগে', 'Best rated first')}</option>
            </select>
          </label>
        </div>
      </div>

      {sort === 'best' && !loading && !error && visible.length > 1 && (
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted -mt-2">
          {t(
            'কমিউনিটি রেটিং থাকা গন্তব্য আগে; বাকিগুলো অতিথি মতামত অনুযায়ী। দুটি রেটিং কখনো মেশানো হয় না।',
            'Destinations with a Community Rating come first; the rest follow by Guest Feedback. The two ratings are never combined.',
          )}
        </p>
      )}

      {loading && <LoadingState label={t('গন্তব্যের তালিকা লোড হচ্ছে…', 'Loading destinations…')} />}
      {!loading && error !== null && <ErrorState error={error} onRetry={reload} />}
      {!loading && !error && savedOnly && data && data.length === 0 && <OfflineEmptyState />}
      {!loading && !error && savedOnly && data && data.length > 0 && <OfflineSavedNotice count={data.length} />}
      {!loading && !error && !savedOnly && data && data.length === 0 && (
        <EmptyState
          title={t('এখনো কোনো প্রকাশিত গন্তব্য নেই', 'No published destinations yet')}
          hint={t('কনটেন্ট প্রকাশিত হলে এখানে দেখা যাবে।', 'Destinations appear here once their content is published.')}
        />
      )}
      {!loading && !error && data && data.length > 0 && visible.length === 0 && (
        <EmptyState
          variant="no-results"
          title={t(`"${query.trim()}"-এর সাথে কোনো গন্তব্য মেলেনি`, `No destination matches "${query.trim()}"`)}
          hint={t('বানান দেখুন বা অন্য শব্দ দিয়ে খুঁজুন; বাংলা ও ইংরেজি দুই নামেই খোঁজা যায়।', 'Check the spelling or try another word; Bangla and English names both work.')}
          action={
            <button type="button" onClick={() => setQuery('')} className="min-h-[44px] px-4 text-sm font-bold underline underline-offset-2 text-forest-primary dark:text-neon-lime">
              {t('খোঁজা মুছুন', 'Clear search')}
            </button>
          }
        />
      )}

      {!loading && !error && visible.length > 0 && (
        <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {visible.map((dest) => (
            <li key={dest.id} className="tonal-card flex flex-col justify-between p-5 gap-4">
              <div className="flex flex-col gap-2.5">
                <div className="flex items-center justify-between gap-2 text-[11px] font-semibold text-on-surface-variant dark:text-on-dark-muted">
                  <span className="inline-flex items-center gap-1">
                    <MapPin size={13} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
                    {pick(language, dest.region_bn, dest.region_en)}
                  </span>
                  {dest.active_advisory_count > 0 && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
                      <AlertTriangle size={12} aria-hidden="true" />
                      {formatNumber(dest.active_advisory_count, language)} {t('সতর্কতা', dest.active_advisory_count === 1 ? 'advisory' : 'advisories')}
                    </span>
                  )}
                </div>
                <h2 className="text-xl font-bold font-title text-on-surface dark:text-on-dark">
                  {pick(language, dest.name_bn, dest.name_en)}
                </h2>
                <p className="text-sm text-on-surface-variant dark:text-on-dark-muted font-body leading-relaxed line-clamp-3">
                  {pick(language, dest.summary_bn, dest.summary_en)}
                </p>
                <RatingSummary community={dest.community_rating} guest={dest.guest_feedback} compact />
              </div>

              <Link
                to={`/destinations/${dest.id}`}
                className="inline-flex items-center justify-center gap-2 min-h-[44px] px-4 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold font-title hover:opacity-95"
              >
                {t('গাইড ও রিভিউ দেখুন', 'View guide & reviews')}
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
