import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Activity, Menu, X, Compass } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { checkBackendHealth } from '../../api/health';
import { PreferenceToggles } from './PreferenceToggles';
import { NotificationBell } from './NotificationBell';

interface NavbarProps {
  onToggleSidebar?: () => void;
  isSidebarOpen?: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({ onToggleSidebar, isSidebarOpen }) => {
  const { t } = useLanguage();
  const location = useLocation();
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    checkBackendHealth()
      .then((res) => {
        if (mounted) setApiOnline(res.status === 'ok');
      })
      .catch(() => {
        if (mounted) setApiOnline(false);
      });
    return () => { mounted = false; };
  }, [location.pathname]);

  return (
    <header className="sticky top-0 z-30 h-16 w-full backdrop-blur-xl bg-canvas-light/85 dark:bg-dark-bg-base/85 border-b border-surface-muted/30 dark:border-dark-surface-2 transition-colors">
      <div className="flex h-full items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Left: Mobile Toggle & Search */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleSidebar}
            className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-xl text-on-surface hover:bg-surface-sage dark:hover:bg-dark-surface-1 lg:hidden transition-colors"
            aria-label={isSidebarOpen ? t('মেনু বন্ধ করুন', 'Close menu') : t('মেনু খুলুন', 'Open menu')}
            aria-expanded={Boolean(isSidebarOpen)}
          >
            {isSidebarOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
          </button>

          <div className="flex items-center gap-2 lg:hidden">
            <Compass className="text-forest-primary dark:text-neon-lime" size={24} aria-hidden="true" />
            <span className="font-title font-bold text-lg text-forest-primary dark:text-neon-lime">
              অভিযাত্রী
            </span>
          </div>

          {/* Global search returns when it is wired to an API (UI-Architecture U10); the destination list has its own filter. */}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Backend API Health Pill */}
          <Link
            to="/health"
            className="flex items-center gap-1.5 px-3 min-h-[44px] rounded-full bg-surface-container dark:bg-dark-surface-2 text-xs hover:opacity-90 transition-opacity"
            aria-label={
              apiOnline === true
                ? t('সার্ভার চালু আছে: সিস্টেম স্ট্যাটাস দেখুন', 'Server online: open system status')
                : apiOnline === false
                  ? t('সার্ভারে সংযোগ নেই: সিস্টেম স্ট্যাটাস দেখুন', 'Server unreachable: open system status')
                  : t('সার্ভার যাচাই হচ্ছে: সিস্টেম স্ট্যাটাস দেখুন', 'Checking the server: open system status')
            }
          >
            <span className="relative flex h-2 w-2">
              <span
                className={`motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  apiOnline === true ? 'bg-emerald-accent' : apiOnline === false ? 'bg-error-alert' : 'bg-accent-green'
                }`}
              ></span>
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  apiOnline === true ? 'bg-emerald-accent' : apiOnline === false ? 'bg-error-alert' : 'bg-accent-green'
                }`}
              ></span>
            </span>
            <Activity size={13} className="text-on-surface-variant dark:text-on-dark-muted" aria-hidden="true" />
            <span className="text-[11px] font-medium hidden sm:inline" aria-hidden="true">
              {apiOnline === true
                ? t('সার্ভার চালু', 'Online')
                : apiOnline === false
                  ? t('সংযোগ নেই', 'Offline')
                  : t('যাচাই হচ্ছে', 'Checking')}
            </span>
          </Link>

          <NotificationBell />
          <PreferenceToggles />
        </div>
      </div>
    </header>
  );
};
