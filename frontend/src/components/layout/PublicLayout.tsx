import React, { Suspense } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { LoadingState } from '../common/StatusViews';
import { Compass } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { PreferenceToggles } from './PreferenceToggles';
import { NetworkBanner, SessionExpiredBanner } from '../common/StatusBanners';
import { PackNotices } from '../offline/PackNotices';

/** Shell for public pages outside the app and the entry frame (now the privacy notice): brand, preferences, no sidebar. */
export const PublicLayout: React.FC = () => {
  const { t } = useLanguage();

  return (
    <div className="min-h-screen flex flex-col text-on-surface dark:text-on-dark">
      <header className="w-full bg-background/80 border-b border-surface-muted/30 dark:border-dark-surface-2">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2.5" aria-label={t('অভিযাত্রী হোম', 'Abhijatri home')}>
            <span className="w-9 h-9 rounded-2xl bg-forest-primary dark:bg-neon-lime flex items-center justify-center text-white dark:text-dark-bg-base">
              <Compass size={20} aria-hidden="true" />
            </span>
            <span className="font-title font-bold text-xl text-forest-primary dark:text-neon-lime">অভিযাত্রী</span>
          </Link>
          <PreferenceToggles />
        </div>
      </header>

      <NetworkBanner />
      <SessionExpiredBanner />
        <PackNotices />
      <main className="flex-1 w-full">
        <Suspense fallback={<LoadingState />}>
            <Outlet />
          </Suspense>
      </main>

      <footer className="bg-background/80 border-t border-surface-muted/30 dark:border-dark-surface-2">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5 text-xs text-on-surface-variant dark:text-on-dark-muted flex flex-wrap gap-x-4 gap-y-1 justify-between">
          <span>{t('অভিযাত্রী: বাংলাদেশ ভ্রমণের বাংলা-প্রথম সঙ্গী', 'Abhijatri: a Bangla-first travel companion for Bangladesh')}</span>
          <span>{t('জরুরি প্রয়োজনে ৯৯৯-এ কল করুন', 'In an emergency, call 999')}</span>
        </div>
      </footer>
    </div>
  );
};
