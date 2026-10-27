import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  MapPin, 
  Calculator, 
  DownloadCloud, 
  Bookmark, 
  MessageSquareText, 
  HeartPulse, 
  Compass,
  LogIn,
  LogOut,
  UserRound
} from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  const { t } = useLanguage();
  const { session, isVerifiedMember, signOut } = useSession();
  const navigate = useNavigate();

  const handleSignOut = () => {
    signOut();
    onClose?.();
    navigate('/');
  };

  const navItems = [
    {
      to: '/overview',
      labelBn: 'সারসংক্ষেপ',
      labelEn: 'Overview',
      icon: LayoutDashboard,
    },
    {
      to: '/destinations',
      labelBn: 'গন্তব্য ও গাইড',
      labelEn: 'Destinations',
      icon: MapPin,
    },
    {
      to: '/planner',
      labelBn: 'খরচ ক্যালকুলেটর',
      labelEn: 'Cost Planner',
      icon: Calculator,
    },
    {
      to: '/offline-packs',
      labelBn: 'অফলাইন প্যাক',
      labelEn: 'Offline Packs',
      icon: DownloadCloud,
    },
    {
      to: '/trips',
      labelBn: 'সংরক্ষিত ট্রিপ',
      labelEn: 'Saved Trips',
      icon: Bookmark,
    },
    {
      to: '/reviews',
      labelBn: 'রিভিউ ও ফিডব্যাক',
      labelEn: 'Reviews',
      icon: MessageSquareText,
    },
    {
      to: '/health',
      labelBn: 'সিস্টেম স্ট্যাটাস',
      labelEn: 'API Health',
      icon: HeartPulse,
    },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-72 bg-surface-sage/70 dark:bg-dark-surface-1 border-r border-surface-muted/30 dark:border-dark-surface-2 flex flex-col justify-between py-6 px-4 transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col gap-6">
          {/* Logo Brand Header */}
          <Link to="/" onClick={onClose} className="flex items-center gap-3 px-3 py-1 rounded-xl" aria-label="অভিযাত্রী / Abhijatri home">
            <div className="w-10 h-10 rounded-2xl bg-forest-primary dark:bg-neon-lime flex items-center justify-center text-white dark:text-dark-bg-base shadow-sm">
              <Compass size={24} />
            </div>
            <div className="flex flex-col">
              <span className="font-title font-bold text-xl text-forest-primary dark:text-neon-lime leading-tight">
                অভিযাত্রী
              </span>
              <span className="font-en text-[11px] font-semibold tracking-wider text-on-surface-variant dark:text-on-dark-muted uppercase">
                Abhijatri Companion
              </span>
            </div>
          </Link>

          {/* Navigation Menu */}
          <nav className="flex flex-col gap-1.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3.5 py-2.5 rounded-xl font-medium text-sm transition-all ${
                      isActive
                        ? 'bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base font-semibold shadow-sm'
                        : 'text-on-surface-variant dark:text-on-dark hover:bg-surface-container dark:hover:bg-dark-surface-2'
                    }`
                  }
                >
                  <Icon size={18} />
                  <span className="font-title text-[15px]">
                    {t(item.labelBn, item.labelEn)}
                  </span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* Offline status card returns with the PWA and IndexedDB work (R12, R13); no claim until then. */}
        {/* Session card: every visitor is a guest until member accounts exist (R04, R05). */}
        <div className="p-3.5 rounded-xl bg-surface-container/80 dark:bg-dark-surface-2 flex flex-col gap-2.5">
          <div className="flex items-center gap-2 text-sm font-semibold text-on-surface dark:text-on-dark">
            <UserRound size={16} className="text-forest-primary dark:text-neon-lime shrink-0" aria-hidden="true" />
            <span className="min-w-0 break-words">
              {session.kind === 'member'
                ? `${session.displayName}${isVerifiedMember ? t(' · যাচাইকৃত সদস্য', ' · Verified Member') : ''}`
                : session.displayName
                  ? t(
                      `স্বাগতম, ${session.displayName}${session.guestTag ? ` · অতিথি ${session.guestTag}` : ''}`,
                      `Welcome, ${session.displayName}${session.guestTag ? ` · Guest ${session.guestTag}` : ''}`,
                    )
                  : session.guestTag
                    ? t(`অতিথি ${session.guestTag}`, `Guest ${session.guestTag}`)
                    : t('অতিথি হিসেবে দেখছেন', 'Browsing as a guest')}
            </span>
          </div>
          {session.kind === 'guest' && (
          <Link
            to="/login"
            onClick={onClose}
            className="inline-flex items-center justify-center gap-2 min-h-[40px] rounded-full border border-forest-primary/40 dark:border-neon-lime/40 text-forest-primary dark:text-neon-lime text-xs font-bold font-title hover:bg-surface-sage dark:hover:bg-dark-surface-1"
          >
            <LogIn size={14} aria-hidden="true" />
            {t('সাইন ইন', 'Sign in')}
          </Link>
          )}
          {session.kind === 'member' && (
            <div className="flex flex-col gap-1 text-xs">
              <Link to="/account/verification" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {isVerifiedMember ? t('যাচাইকৃত সদস্য ✓', 'Verified Member ✓') : t('যাচাইকৃত সদস্য হোন', 'Become a Verified Member')}
              </Link>
              <Link to="/account/appeals" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {t('আপিল', 'Appeals')}
              </Link>
            </div>
          )}
          {/* A member or a named guest can sign out; an anonymous guest has nothing to sign out of. */}
          {(session.kind === 'member' || session.displayName) && (
          <button
            type="button"
            onClick={handleSignOut}
            className="inline-flex items-center justify-center gap-2 min-h-[40px] rounded-full border border-forest-primary/40 dark:border-neon-lime/40 text-forest-primary dark:text-neon-lime text-xs font-bold font-title hover:bg-surface-sage dark:hover:bg-dark-surface-1"
          >
            <LogOut size={14} aria-hidden="true" />
            {t('সাইন আউট', 'Sign out')}
          </button>
          )}
        </div>
      </aside>
    </>
  );
};
