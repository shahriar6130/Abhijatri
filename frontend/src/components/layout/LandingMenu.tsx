import React, { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';

type Item = { to: string; label: [string, string] };

/**
 * The front page's hamburger menu (UI refresh, 22 Nov 2026): the app's main pages, since the front
 * page has no sidebar. A disclosure: the button says whether it is open, Escape or a press outside
 * closes it, and focus returns to the button.
 */
export const LandingMenu: React.FC = () => {
  const { t } = useLanguage();
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  const items: Item[] = [
    { to: '/overview', label: ['সারসংক্ষেপ', 'Overview'] },
    { to: '/destinations', label: ['গন্তব্য ও গাইড', 'Destinations & guides'] },
    { to: '/reviews/write', label: ['রিভিউ লিখুন', 'Write a review'] },
    { to: '/account/reviews', label: ['আমার রিভিউ', 'My reviews'] },
    { to: '/offline-packs', label: ['অফলাইন প্যাক', 'Offline packs'] },
    { to: '/tours', label: ['ট্যুর ও ট্যুরমেটস', 'Tours & TourMates'] },
    ...(session.kind === 'member' ? [] : [{ to: '/login', label: ['সাইন ইন', 'Sign in'] as [string, string] }]),
    { to: '/privacy', label: ['গোপনীয়তা', 'Privacy'] },
  ];

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={open ? t('মেনু বন্ধ করুন', 'Close menu') : t('মেনু খুলুন', 'Open menu')}
        onClick={() => setOpen((o) => !o)}
        className="w-11 h-11 -ml-2 rounded-xl flex flex-col items-start justify-center gap-[5px] pl-2.5 text-foreground hover:bg-muted"
      >
        <span aria-hidden="true" className="block h-0.5 w-6 rounded-full bg-current" />
        <span aria-hidden="true" className="block h-0.5 w-4 rounded-full bg-current" />
      </button>
      {open && (
        <nav
          id={id}
          aria-label={t('প্রধান মেনু', 'Main menu')}
          className="absolute left-0 top-full mt-2 z-20 w-64 rounded-2xl bg-popover text-popover-foreground border border-border shadow-[0_16px_48px_rgb(0_0_0/0.14)] p-2"
        >
          <ul className="flex flex-col">
            {items.map((item) => (
              <li key={item.to}>
                <Link
                  to={item.to}
                  onClick={() => setOpen(false)}
                  className="flex items-center min-h-11 px-3 rounded-xl text-sm text-foreground hover:bg-muted"
                >
                  {t(...item.label)}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </div>
  );
};
