import React, { useEffect, useState } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  MapPin, 
  Calculator, 
  DownloadCloud, 
  Bookmark, 
  MessageSquareText, 
  ChevronDown,
  ListChecks,
  PenSquare,
  Compass,
  LogIn,
  LogOut,
  UserRound
  ,Users
} from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import { buttonVariants } from '@/components/ui/button';
import { formatNumber } from '../../utils/format';
import { useGuardedSignOut } from '../reviews/useGuardedSignOut';

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
  /** Unsent review drafts on this device, shown on "Write a review" (R15). */
  unsentDrafts?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose, unsentDrafts = 0 }) => {
  const { language, t } = useLanguage();
  const { session, isVerifiedMember, status } = useSession();
  // Warns first when a member has unsent review drafts on this device (guideline 6.7).
  const guardedSignOut = useGuardedSignOut();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // The Reviews group opens by itself whenever one of its pages is showing.
  const inReviews = pathname.startsWith('/reviews') || pathname.startsWith('/account/reviews');
  const [reviewsOpen, setReviewsOpen] = useState(inReviews);
  useEffect(() => {
    if (inReviews) setReviewsOpen(true);
  }, [inReviews]);

  const handleSignOut = () => {
    void guardedSignOut.request(() => {
      onClose?.();
      navigate('/');
    });
  };

  type NavChild = { to: string; labelBn: string; labelEn: string; icon: typeof Compass; count?: number };
  const navItems: { to: string; labelBn: string; labelEn: string; icon: typeof Compass; soon?: boolean; children?: NavChild[] }[] = [
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
      labelBn: 'খরচ পরিকল্পনা',
      labelEn: 'Cost planner',
      icon: Calculator,
      soon: true,
    },
    {
      to: '/offline-packs',
      labelBn: 'অফলাইন প্যাক',
      labelEn: 'Offline packs',
      icon: DownloadCloud,
    },
    {
      to: '/trips',
      labelBn: 'সংরক্ষিত ভ্রমণ',
      labelEn: 'Saved trips',
      icon: Bookmark,
      soon: true,
    },
    {
      to: '/tours',
      labelBn: 'ট্যুর ও ট্যুরমেটস',
      labelEn: 'Tours & TourMates',
      icon: Users,
    },
    {
      to: '/reviews',
      labelBn: 'রিভিউ',
      labelEn: 'Reviews',
      icon: MessageSquareText,
      children: [
        { to: '/reviews/write', labelBn: 'রিভিউ লিখুন', labelEn: 'Write a review', icon: PenSquare, count: unsentDrafts },
        // A member finds their reviews in a list; only a guest, who has no account, needs the
        // review ID and receipt (Phase 1 update 4, Decisions 2026-11-11).
        { to: '/account/reviews', labelBn: 'আমার রিভিউ', labelEn: 'My reviews', icon: ListChecks },
      ],
    },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 w-72 bg-background/85 border-r border-surface-muted/30 dark:border-dark-surface-2 flex flex-col justify-between py-6 px-4 transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex flex-col gap-6">
          {/* Logo Brand Header */}
          <Link to="/" onClick={onClose} className="flex items-center gap-3 px-3 py-1 rounded-xl" aria-label={t('অভিযাত্রী হোম', 'Abhijatri home')}>
            <div className="w-10 h-10 rounded-2xl bg-forest-primary dark:bg-neon-lime flex items-center justify-center text-white dark:text-dark-bg-base shadow-xs">
              <Compass size={24} aria-hidden="true" />
            </div>
            <div className="flex flex-col">
              <span className="font-title font-bold text-xl text-forest-primary dark:text-neon-lime leading-tight">
                অভিযাত্রী
              </span>
              <span className="text-[11px] font-semibold text-on-surface-variant dark:text-on-dark-muted">
                {t('ভ্রমণ সঙ্গী', 'Travel companion')}
              </span>
            </div>
          </Link>

          {/* Navigation Menu */}
          <nav className="flex flex-col gap-1.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              if (item.children) {
                const groupId = 'sidebar-group-reviews';
                return (
                  <div key={item.to} className="flex flex-col gap-1">
                    {/* A disclosure button, not a link: it shows the two review pages below it. */}
                    <button
                      type="button"
                      aria-expanded={reviewsOpen}
                      aria-controls={groupId}
                      onClick={() => setReviewsOpen((open) => !open)}
                      className={`flex w-full items-center gap-3 px-3.5 py-2.5 rounded-xl font-medium text-sm text-left cursor-pointer transition-colors ${
                        inReviews
                          ? 'text-forest-primary dark:text-neon-lime font-semibold'
                          : 'text-on-surface-variant dark:text-on-dark'
                      } hover:bg-surface-container dark:hover:bg-dark-surface-2`}
                    >
                      <Icon size={18} aria-hidden="true" />
                      <span className="font-title text-[15px]">{t(item.labelBn, item.labelEn)}</span>
                      {!reviewsOpen && unsentDrafts > 0 && (
                        <span
                          className="ml-auto min-w-6 px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 text-[11px] font-bold text-center"
                          aria-label={t(`${formatNumber(unsentDrafts, 'bn')}টি না পাঠানো খসড়া`, `${unsentDrafts} unsent draft${unsentDrafts === 1 ? '' : 's'}`)}
                        >
                          {formatNumber(unsentDrafts, language)}
                        </span>
                      )}
                      <ChevronDown
                        size={16}
                        aria-hidden="true"
                        className={`${!reviewsOpen && unsentDrafts > 0 ? 'ml-1' : 'ml-auto'} shrink-0 motion-safe:transition-transform ${reviewsOpen ? 'rotate-180' : ''}`}
                      />
                    </button>
                    {reviewsOpen && (
                      <ul id={groupId} className="ml-5 pl-3 border-l border-border flex flex-col gap-1">
                        {item.children.map((child) => {
                          const ChildIcon = child.icon;
                          return (
                            <li key={child.to}>
                              <NavLink
                                to={child.to}
                                onClick={onClose}
                                className={({ isActive }) =>
                                  `flex items-center gap-2.5 px-3 py-2 min-h-11 rounded-xl text-sm transition-colors ${
                                    isActive
                                      ? 'bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base font-semibold shadow-xs'
                                      : 'text-on-surface-variant dark:text-on-dark hover:bg-surface-container dark:hover:bg-dark-surface-2'
                                  }`
                                }
                              >
                                <ChildIcon size={16} aria-hidden="true" />
                                <span className="font-title">{t(child.labelBn, child.labelEn)}</span>
                                {Boolean(child.count) && (
                                  <span
                                    className="ml-auto min-w-6 px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-200 text-[11px] font-bold text-center"
                                    aria-label={t(`${formatNumber(child.count!, 'bn')}টি না পাঠানো খসড়া`, `${child.count} unsent draft${child.count === 1 ? '' : 's'}`)}
                                  >
                                    {formatNumber(child.count!, language)}
                                  </span>
                                )}
                              </NavLink>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              }
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3.5 py-2.5 rounded-xl font-medium text-sm transition-all ${
                      isActive
                        ? 'bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base font-semibold shadow-xs'
                        : 'text-on-surface-variant dark:text-on-dark hover:bg-surface-container dark:hover:bg-dark-surface-2'
                    }`
                  }
                >
                  <Icon size={18} aria-hidden="true" />
                  <span className="font-title text-[15px]">
                    {t(item.labelBn, item.labelEn)}
                  </span>
                  {item.soon && (
                    <span className="ml-auto px-2 py-0.5 rounded-full bg-muted text-muted-foreground text-[10px] font-bold">
                      {t('শীঘ্রই', 'Soon')}
                    </span>
                  )}
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
            <span className="min-w-0 wrap-break-word">
              {status === 'unreachable'
                ? t('সংযোগ নেই: সাইন-ইন যাচাই করা যাচ্ছে না', 'No connection: sign-in cannot be checked')
                : session.kind === 'member'
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
          {status !== 'unreachable' && session.kind === 'guest' && (
          <Link
            to="/login"
            onClick={onClose}
            className={buttonVariants({ variant: 'outline', size: 'sm', className: 'w-full' })}
          >
            <LogIn size={14} aria-hidden="true" />
            {t('সাইন ইন', 'Sign in')}
          </Link>
          )}
          {session.kind === 'member' && (
            <div className="flex flex-col gap-1 text-xs">
              <Link to="/verify" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {isVerifiedMember ? t('যাচাইকৃত সদস্য ✓', 'Verified Member ✓') : t('যাচাইকৃত সদস্য হোন', 'Become a Verified Member')}
              </Link>
              <Link to="/account/reviews" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {t('আমার রিভিউ', 'My reviews')}
              </Link>
              <Link to="/account/reports" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {t('আমার রিপোর্ট', 'My reports')}
              </Link>
              <Link to="/account/appeals" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {t('আপিল', 'Appeals')}
              </Link>
              <Link to="/account/notifications" onClick={onClose} className="font-bold text-forest-primary dark:text-neon-lime hover:underline">
                {t('বিজ্ঞপ্তি ও ইমেইল', 'Notifications and email')}
              </Link>
            </div>
          )}
          {/* A member signs out of an account. A named guest has no account, so the same control is
              labelled "Exit" (it forgets the name). An anonymous guest has nothing to leave. */}
          {(session.kind === 'member' || session.displayName) && (
          <button
            type="button"
            onClick={handleSignOut}
            className={buttonVariants({ variant: 'outline', size: 'sm', className: 'w-full' })}
          >
            <LogOut size={14} aria-hidden="true" />
            {session.kind === 'member' ? t('সাইন আউট', 'Sign out') : t('বের হোন', 'Exit')}
          </button>
          )}
        </div>
      </aside>
      {guardedSignOut.dialog}
    </>
  );
};
