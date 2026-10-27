import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Search, Activity, Menu, X, Compass } from 'lucide-react';
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
            className="p-2 rounded-xl text-on-surface hover:bg-surface-sage dark:hover:bg-dark-surface-1 lg:hidden transition-colors"
            aria-label="Toggle Navigation"
          >
            {isSidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>

          <div className="flex items-center gap-2 lg:hidden">
            <Compass className="text-forest-primary dark:text-neon-lime" size={24} />
            <span className="font-title font-bold text-lg text-forest-primary dark:text-neon-lime">
              অভিযাত্রী
            </span>
          </div>

          <div className="hidden sm:flex relative items-center w-64 lg:w-80">
            <Search className="absolute left-3.5 text-on-surface-variant/70 dark:text-on-dark-muted" size={17} />
            <input
              type="text"
              placeholder={t('গন্তব্য, রুট বা এলাকা খুঁজুন...', 'Search destinations, trails, costs...')}
              className="w-full pl-10 pr-4 py-1.5 text-sm rounded-full bg-surface-sage/50 dark:bg-dark-surface-1 border border-surface-muted/40 dark:border-dark-surface-2 text-on-surface dark:text-on-dark placeholder:text-on-surface-variant/60 dark:placeholder:text-on-dark-muted focus:outline-none focus:ring-1 focus:ring-forest-primary dark:focus:ring-neon-lime transition-all"
            />
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Backend API Health Pill */}
          <Link
            to="/health"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-container dark:bg-dark-surface-2 text-xs hover:opacity-90 transition-opacity"
            title={t('ব্যাকএন্ড হেলথ চেক', 'Check Backend Health')}
          >
            <span className="relative flex h-2 w-2">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  apiOnline === true ? 'bg-emerald-accent' : apiOnline === false ? 'bg-error-alert' : 'bg-accent-green'
                }`}
              ></span>
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  apiOnline === true ? 'bg-emerald-accent' : apiOnline === false ? 'bg-error-alert' : 'bg-accent-green'
                }`}
              ></span>
            </span>
            <Activity size={13} className="text-on-surface-variant dark:text-on-dark-muted" />
            <span className="font-en text-[11px] font-medium hidden sm:inline">
              {apiOnline === true ? 'API Live' : apiOnline === false ? 'API Offline' : 'Checking'}
            </span>
          </Link>

          <NotificationBell />
          <PreferenceToggles />
        </div>
      </div>
    </header>
  );
};
