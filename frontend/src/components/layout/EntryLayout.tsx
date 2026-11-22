import React, { Suspense, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useOutlet } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Compass,
  ImagePlus,
  LogIn,
  MapPin,
  MessageSquareText,
  Phone,
  ShieldAlert,
  UserRound,
} from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import { useTheme } from '../../context/ThemeContext';
import { ImageCredit } from '../common/ImageCredit';
import { LoadingState } from '../common/StatusViews';
import { NetworkBanner, SessionExpiredBanner } from '../common/StatusBanners';
import { PackNotices } from '../offline/PackNotices';
import { PreferenceToggles } from './PreferenceToggles';
import Velaris from '@/components/ui/velaris';
import { allDestinationImages } from '../../data/destinationImages';
import { buttonVariants } from '@/components/ui/button';

/** Seconds each hero photo stays before the next one. */
const SLIDE_SECONDS = 7;

/** The licensed destination photos, in a fixed order. They are bundled, so the hero works offline too. */
const SLIDES = allDestinationImages();

/** Account pages that open in the form side; which choice each belongs to. */
const FORM_PAGES: Record<string, 'guest' | 'member'> = {
  '/guest': 'guest',
  '/login': 'member',
  '/register': 'member',
  '/verify-email': 'member',
  '/forgot-password': 'member',
  '/reset-password': 'member',
};

/**
 * The green background behind the account forms (owner, 22 Nov 2026: "the greenish gradient it had
 * before"). Light: mint greens, a step stronger than the app-wide background removed earlier that day,
 * so the curved edge shows against the white side beside it. Dark: deep greens on a green-tinted near-black, so the curve also shows in dark mode. Muted text
 * (#5C5C5C) keeps at least 5.6:1 on the strongest light green (#BBF7D0); the forms sit in white boxes.
 */
const GREEN_LIGHT = { bg: '#f0fdf4', colors: ['#bbf7d0', '#dcfce7', '#a7f3d0', '#f0fdf4'] };
const GREEN_DARK = { bg: '#12201a', colors: ['#052e16', '#0f3d22', '#022c22', '#12201a'] };

/** Low memory, few cores or Data Saver: one still frame instead of an animation. */
function lowEndDevice(): boolean {
  if (typeof navigator === 'undefined') return false;
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } };
  return (nav.deviceMemory !== undefined && nav.deviceMemory < 4) || (nav.hardwareConcurrency || 8) <= 4 || nav.connection?.saveData === true;
}
const STILL = lowEndDevice();

type Capability = { icon: typeof MapPin; bn: string; en: string };

/** What a Guest can do (Execution.md rules 1 to 4; Review.md 2.1). */
const GUEST: Capability[] = [
  { icon: MapPin, bn: 'গন্তব্য গাইড, মৌসুম ও বিধিনিষেধ দেখুন', en: 'Read destination guides, seasons and restrictions' },
  { icon: ShieldAlert, bn: 'সূত্র ও তারিখসহ নিরাপত্তা সতর্কতা', en: 'See dated safety advisories with sources' },
  { icon: Phone, bn: 'জরুরি যোগাযোগের নম্বর', en: 'Find emergency contact numbers' },
  { icon: MessageSquareText, bn: 'শুধু লেখায় রিভিউ দিন (মডারেশনের পর প্রকাশ)', en: 'Write text-only reviews, published after moderation' },
];

/** What an account adds (Review.md 2.1, 6.1, 8). */
const MEMBER: Capability[] = [
  { icon: UserRound, bn: 'নিজের অ্যাকাউন্টে রিভিউ রাখুন ও পরিচালনা করুন', en: 'Keep and manage reviews in your own account' },
  { icon: BadgeCheck, bn: 'যাচাইকৃত সদস্যের রেটিং কমিউনিটি রেটিংয়ে গণনা হয়', en: 'Verified Member ratings count towards Community Rating' },
  { icon: ImagePlus, bn: 'যাচাইকৃত সদস্যরা রিভিউতে ছবি যোগ করতে পারেন', en: 'Verified Members can add photos to reviews' },
];

const CapabilityList: React.FC<{ items: Capability[] }> = ({ items }) => {
  const { t } = useLanguage();
  return (
    <ul className="flex flex-col gap-2.5 lg:gap-[clamp(0.25rem,1vh,0.625rem)]">
      {items.map(({ icon: Icon, bn, en }) => (
        <li key={en} className="flex items-start gap-3 text-sm">
          <span className="mt-0.5 w-7 h-7 shrink-0 rounded-full bg-muted text-foreground flex items-center justify-center">
            <Icon size={15} aria-hidden="true" />
          </span>
          <span className="text-foreground">{t(bn, en)}</span>
        </li>
      ))}
    </ul>
  );
};

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const changed = () => setMatch(list.matches);
    list.addEventListener('change', changed);
    return () => list.removeEventListener('change', changed);
  }, [query]);
  return match;
}

/**
 * The photos change by themselves (owner decision, 22 Nov 2026: no controls in the hero). They stay
 * still while the tab is hidden, and for visitors whose device asks for reduced motion.
 */
function useAutoSlide(count: number, running: boolean): number {
  const [current, setCurrent] = useState(0);
  const still = useMedia('(prefers-reduced-motion: reduce)');
  useEffect(() => {
    if (still || !running || count < 2) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setCurrent((n) => (n + 1) % count);
    }, SLIDE_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [still, running, count]);
  return count > 0 ? current % count : 0;
}

type PhoneView = 'hero' | 'start';

/**
 * The front page and the account pages in one frame (owner, 22 Nov 2026), so they can slide into each
 * other. A row of three sides: [photo hero][guest or member choice][account form on green].
 *   Computer: two sides at a time. The front page shows hero and choice; an account page slides the
 *   hero out to the left, the choice into the left half, and the form in from the right.
 *   Phone: one side at a time. On the front page a switch moves between hero and choice; an account
 *   page slides its form in, and "Back" slides back to the choice.
 * The page is exactly one screen high; the form side scrolls when its content is taller.
 */
export const EntryLayout: React.FC = () => {
  const { language, t } = useLanguage();
  const { session } = useSession();
  const { theme } = useTheme();
  const { pathname } = useLocation();
  const outlet = useOutlet();
  const wide = useMedia('(min-width: 1024px)');
  const choice = FORM_PAGES[pathname];
  const home = choice === undefined;
  const member = session.kind === 'member';
  const [phoneView, setPhoneView] = useState<PhoneView>('hero');
  const index = useAutoSlide(SLIDES.length, home);
  const [, image] = SLIDES[index] ?? [];

  // Arriving at an account page always means the choice has been made: going back shows the choice.
  useEffect(() => {
    if (!home) setPhoneView('start');
  }, [home]);

  // The form keeps its last page while it slides out, then empties (the slide takes 700 ms).
  const [leaving, setLeaving] = useState<React.ReactNode>(null);
  const last = useRef<React.ReactNode>(null);
  useEffect(() => {
    if (!home) {
      last.current = outlet;
      setLeaving(null);
      return;
    }
    if (!last.current) return;
    setLeaving(last.current);
    last.current = null;
    const timer = window.setTimeout(() => setLeaving(null), 800);
    return () => window.clearTimeout(timer);
  }, [home, outlet]);

  // After the slide, put focus on the form side so keyboard and screen-reader users land on it.
  const formPanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (home) return;
    const timer = window.setTimeout(() => formPanel.current?.focus({ preventScroll: true }), 450);
    return () => window.clearTimeout(timer);
  }, [home, pathname]);

  // Load the account pages in the background, so the form is ready when it slides in.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void import('../../pages/SignInPage');
      void import('../../pages/RegisterPage');
    }, 1500);
    return () => window.clearTimeout(timer);
  }, []);

  // Which side the screen shows. Sides that are slid away cannot be reached with Tab or a screen reader.
  const visible = (side: 'hero' | 'choice' | 'form') =>
    wide ? (home ? side !== 'form' : side !== 'hero') : home ? (phoneView === 'hero' ? side === 'hero' : side === 'choice') : side === 'form';
  const away = (side: 'hero' | 'choice' | 'form') => (visible(side) ? {} : ({ inert: '', 'aria-hidden': true } as object));

  const phoneShift = !home ? '-translate-x-2/3' : phoneView === 'start' ? '-translate-x-1/3' : 'translate-x-0';
  const wideShift = home ? 'lg:translate-x-0' : 'lg:-translate-x-[36.709%]';

  const option = (active: boolean) =>
    `flex flex-col gap-4 lg:gap-[clamp(0.5rem,1.5vh,1.125rem)] rounded-3xl p-5 -mx-5 lg:py-[clamp(0.625rem,2vh,1.25rem)] transition-colors ${
      active ? 'bg-primary/10 ring-1 ring-primary/40' : ''
    }`;

  const switchButton = (side: PhoneView, label: [string, string]) => (
    <button
      type="button"
      aria-pressed={phoneView === side}
      aria-controls={side === 'hero' ? 'entry-hero' : 'entry-choice'}
      onClick={() => setPhoneView(side)}
      className={`relative z-10 flex-1 min-h-11 px-4 rounded-full text-sm font-semibold transition-colors ${
        phoneView === side ? 'text-primary-foreground' : 'text-background/80 hover:text-background'
      }`}
    >
      {t(...label)}
    </button>
  );

  const green = theme === 'dark' ? GREEN_DARK : GREEN_LIGHT;

  return (
    <div className="h-dvh flex flex-col overflow-clip bg-background text-foreground">
      <NetworkBanner />
      <SessionExpiredBanner />
      <PackNotices />

      {/* `clip`, not `hidden`: a field that focuses itself on a page sliding in must not scroll this row sideways. */}
      <div className="relative flex-1 min-h-0 overflow-clip">
        <div
          className={`flex h-full w-[300%] lg:w-[158%] motion-safe:transition-transform motion-safe:duration-700 motion-safe:ease-[cubic-bezier(0.22,1,0.36,1)] ${phoneShift} ${wideShift}`}
        >
          {/* ---------- Hero ---------- */}
          <section
            id="entry-hero"
            aria-labelledby="landing-title"
            {...away('hero')}
            className="relative isolate overflow-hidden w-1/3 lg:w-[36.709%] h-full shrink-0 rounded-b-[2rem] lg:rounded-bl-none lg:rounded-r-[4.5rem] bg-foreground text-white flex flex-col"
          >
            {SLIDES.map(([nameEn, s], i) => {
              // Keep the previous, current and next photo in the page: the next one loads before it fades in.
              const near = i === index || i === (index + 1) % SLIDES.length || i === (index - 1 + SLIDES.length) % SLIDES.length;
              if (!near) return null;
              return (
                <img
                  key={nameEn}
                  src={s.src}
                  srcSet={`${s.srcSmall} 480w, ${s.src} 1024w`}
                  sizes="(min-width: 1024px) 58vw, 100vw"
                  width={s.width}
                  height={s.height}
                  alt={i === index ? s.alt[language] : ''}
                  aria-hidden={i === index ? undefined : true}
                  fetchPriority={i === index ? 'high' : 'low'}
                  className={`absolute inset-0 -z-20 h-full w-full object-cover motion-safe:transition-opacity motion-safe:duration-1000 ${i === index ? 'opacity-100' : 'opacity-0'}`}
                />
              );
            })}
            {/* Darkens the photo where the text sits, so white text keeps its contrast on any image. */}
            <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-t from-black/85 via-black/35 to-black/40" />
            <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-r from-black/45 to-transparent" />

            <div className="flex-1 min-h-0 flex flex-col gap-6 px-7 pt-7 pb-24 sm:px-10 sm:pt-10 lg:p-[clamp(1.75rem,5.5vh,3.5rem)] lg:gap-[clamp(1rem,3vh,2rem)]">
              <Link to="/" className="self-start inline-flex items-center gap-3 min-h-11" aria-label={t('অভিযাত্রী হোম', 'Abhijatri home')}>
                <span className="w-10 h-10 rounded-full border-2 border-white/90 flex items-center justify-center">
                  <Compass size={20} aria-hidden="true" />
                </span>
                <span className="font-title text-xl font-bold">অভিযাত্রী</span>
              </Link>

              <div className="mt-auto flex flex-col gap-4 lg:gap-[clamp(0.75rem,2.2vh,1.25rem)] max-w-xl">
                <h1 id="landing-title" className="text-4xl sm:text-5xl lg:text-[clamp(2.25rem,6.4vh,3.75rem)] font-bold font-title leading-[1.08] text-balance">
                  {t('যাওয়ার আগে জানুন, ফিরে এসে জানান', 'Know before you go. Share when you are back.')}
                </h1>
                <p className="text-base sm:text-lg lg:text-[clamp(0.95rem,2.1vh,1.125rem)] leading-relaxed text-white/85 max-w-lg">
                  {t(
                    'সূত্র ও তারিখসহ গন্তব্য গাইড, নিরাপত্তা সতর্কতা, জরুরি নম্বর আর মডারেশন করা ভ্রমণকারীর রিভিউ, বাংলায় ও ইংরেজিতে।',
                    'Source-dated destination guides, safety advisories, emergency numbers and moderated traveller reviews, in Bangla and English.',
                  )}
                </p>
              </div>

              {image && (
                <div className="flex flex-col gap-1.5">
                  {/* Shows where the slideshow is; not a control. */}
                  <div className="flex gap-1.5 w-40 sm:w-56" aria-hidden="true">
                    {SLIDES.map(([nameEn], i) => (
                      <span key={nameEn} className={`flex-1 h-0.5 rounded-full transition-colors ${i === index ? 'bg-white' : 'bg-white/35'}`} />
                    ))}
                  </div>
                  <p className="inline-flex items-center gap-1.5 min-h-8 text-sm font-semibold">
                    <MapPin size={14} aria-hidden="true" />
                    {image.place[language]}
                  </p>
                  <p className="text-[11px] text-white/70">
                    <ImageCredit credit={image.credit} />
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* ---------- Guest or member ---------- */}
          <section
            id="entry-choice"
            aria-label={t('কীভাবে শুরু করবেন', 'How to start')}
            {...away('choice')}
            className="w-1/3 lg:w-[26.582%] h-full shrink-0 min-w-0 overflow-y-auto flex flex-col gap-6 px-5 pt-6 pb-24 sm:px-9 sm:pt-8 lg:px-[clamp(1.5rem,3vw,3rem)] lg:py-[clamp(1rem,3vh,2.5rem)] lg:gap-[clamp(0.75rem,2.6vh,2rem)]"
          >
            {/* Front page: the switches. An account page: Back (the brand and switches move to the form side). */}
            <div className="flex items-center justify-between gap-3 min-h-11">
              {home ? (
                <span />
              ) : (
                <Link to="/" className="inline-flex items-center gap-1.5 min-h-11 px-3 -ml-3 rounded-full text-sm font-semibold text-foreground hover:bg-muted">
                  <ArrowLeft size={16} aria-hidden="true" />
                  {t('ফিরে যান', 'Back')}
                </Link>
              )}
              {home && <PreferenceToggles />}
            </div>

            <div className="flex-1 w-full max-w-md mx-auto flex flex-col justify-center gap-5 lg:gap-[clamp(0.5rem,2vh,1.5rem)]">
              <div className={option(choice === 'guest')}>
                <h2 className="text-2xl lg:text-[clamp(1.25rem,3vh,1.5rem)] font-bold font-title text-foreground">{t('অতিথি হিসেবে দেখুন', 'Explore as a guest')}</h2>
                <CapabilityList items={GUEST} />
                {member && (
                  <p className="text-xs text-muted-foreground wrap-anywhere">
                    {t(`আপনি ${session.displayName} হিসেবে সাইন ইন আছেন; অতিথি হতে আগে সাইন আউট করতে হবে।`, `You are signed in as ${session.displayName}; guest mode needs you to sign out first.`)}
                  </p>
                )}
                <Link
                  to="/guest"
                  aria-current={choice === 'guest' ? 'page' : undefined}
                  className={buttonVariants({ size: 'lg', className: 'rounded-xl' })}
                >
                  {t('অতিথি হিসেবে চালিয়ে যান', 'Continue as guest')}
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
              </div>

              <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
                <span className="h-px flex-1 bg-border" />
                {t('অথবা', 'or')}
                <span className="h-px flex-1 bg-border" />
              </div>

              <div className={option(choice === 'member')}>
                <h2 className="text-2xl lg:text-[clamp(1.25rem,3vh,1.5rem)] font-bold font-title text-foreground">{t('সদস্য হিসেবে সাইন ইন', 'Sign in as a member')}</h2>
                <CapabilityList items={MEMBER} />
                {member ? (
                  <Link to="/overview" className={buttonVariants({ variant: 'outline', size: 'lg', className: 'rounded-xl' })}>
                    {t('অ্যাপে যান', 'Open the app')}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                ) : (
                  <Link
                    to="/login"
                    aria-current={pathname === '/login' ? 'page' : undefined}
                    className={buttonVariants({ variant: 'outline', size: 'lg', className: 'rounded-xl' })}
                  >
                    <LogIn size={16} aria-hidden="true" />
                    {t('সাইন ইন', 'Sign in')}
                  </Link>
                )}
              </div>
            </div>
          </section>

          {/* ---------- Account form on the green background ---------- */}
          <section
            id="entry-form"
            aria-label={t('অ্যাকাউন্ট', 'Account')}
            {...away('form')}
            className="w-1/3 lg:w-[36.709%] h-full shrink-0 lg:rounded-l-[4.5rem] overflow-hidden lg:shadow-[-12px_0_40px_rgb(0_0_0/0.06)]"
          >
            <Velaris bg={green.bg} colors={green.colors} speed={3.5} grain={0.04} animate={!STILL && !home} className="h-full">
              <div ref={formPanel} tabIndex={-1} className="h-full overflow-y-auto outline-none">
                <div className="min-h-full flex flex-col px-4 sm:px-6 lg:pl-16 lg:pr-12 pt-4 lg:pt-[clamp(1.25rem,4vh,2.5rem)] pb-6">
                  <div className="flex items-center justify-between gap-3">
                    {/* On a phone the choice is off screen, so Back stays here. */}
                    <Link to="/" className="lg:hidden inline-flex items-center gap-1.5 min-h-11 px-3 -ml-3 rounded-full text-sm font-semibold text-foreground hover:bg-muted">
                      <ArrowLeft size={16} aria-hidden="true" />
                      {t('ফিরে যান', 'Back')}
                    </Link>
                    <Link to="/" aria-label={t('অভিযাত্রী হোম', 'Abhijatri home')} className="hidden lg:inline-flex items-center gap-2.5 min-h-11">
                      <span className="w-9 h-9 rounded-full border-2 border-foreground flex items-center justify-center">
                        <Compass size={18} aria-hidden="true" />
                      </span>
                      <span className="font-title text-lg font-bold">অভিযাত্রী</span>
                    </Link>
                    <PreferenceToggles />
                  </div>
                  <div className="flex-1 flex flex-col justify-center">
                    <Suspense fallback={<LoadingState />}>{home ? (leaving ?? last.current) : outlet}</Suspense>
                  </div>
                </div>
              </div>
            </Velaris>
          </section>
        </div>

        {/* Phone, front page only: slides between the hero and the choice. The green thumb marks the side on screen. */}
        {home && (
          <div
            role="group"
            aria-label={t('প্রথম পাতার অংশ', 'Front page sections')}
            className="lg:hidden absolute bottom-4 left-1/2 -translate-x-1/2 z-20 w-[min(20rem,calc(100%-2rem))] flex p-1 rounded-full bg-foreground/90 backdrop-blur shadow-[0_8px_24px_rgb(0_0_0/0.25)]"
          >
            <span
              aria-hidden="true"
              className={`absolute top-1 bottom-1 left-1 w-[calc(50%-0.25rem)] rounded-full bg-primary motion-safe:transition-transform motion-safe:duration-300 ${
                phoneView === 'start' ? 'translate-x-full' : 'translate-x-0'
              }`}
            />
            {switchButton('hero', ['পরিচিতি', 'About'])}
            {switchButton('start', ['শুরু করুন', 'Get started'])}
          </div>
        )}
      </div>
    </div>
  );
};
