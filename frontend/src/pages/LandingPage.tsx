import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
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
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { ImageCredit } from '../components/common/ImageCredit';
import { PreferenceToggles } from '../components/layout/PreferenceToggles';
import { allDestinationImages } from '../data/destinationImages';
import { buttonVariants } from '@/components/ui/button';

/** Seconds each hero photo stays before the next one. */
const SLIDE_SECONDS = 7;

/** The licensed destination photos, in a fixed order. They are bundled, so the hero works offline too. */
const SLIDES = allDestinationImages();

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
    <ul className="flex flex-col gap-2.5">
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

/**
 * The photos change by themselves (owner decision, 22 Nov 2026: no controls in the hero). They stay
 * still while the tab is hidden, and for visitors whose device asks for reduced motion.
 */
function useAutoSlide(count: number): number {
  const [current, setCurrent] = useState(0);
  const [still, setStill] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const changed = () => setStill(query.matches);
    query.addEventListener('change', changed);
    return () => query.removeEventListener('change', changed);
  }, []);

  useEffect(() => {
    if (still || count < 2) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setCurrent((n) => (n + 1) % count);
    }, SLIDE_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [still, count]);

  return count > 0 ? current % count : 0;
}

/** True from the `lg` breakpoint (1024 px), where both sides are shown together. */
function useWide(): boolean {
  const query = '(min-width: 1024px)';
  const [wide, setWide] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const changed = () => setWide(list.matches);
    list.addEventListener('change', changed);
    return () => list.removeEventListener('change', changed);
  }, []);
  return wide;
}

type View = 'hero' | 'start';

/**
 * The front page (UI refresh, 22 Nov 2026), after the owner's reference.
 * Desktop: the photo hero fills the left side and the guest or member choice the right; the page is
 * exactly one screen high with the footer, and sizes follow the screen height so nothing scrolls.
 * Phone: one side at a time; a switch at the bottom slides between them.
 */
export const LandingPage: React.FC = () => {
  const { language, t } = useLanguage();
  const { session } = useSession();
  const index = useAutoSlide(SLIDES.length);
  const [, image] = SLIDES[index] ?? [];
  const member = session.kind === 'member';
  const wide = useWide();
  const [view, setView] = useState<View>('hero');
  // On a phone the side that is slid away cannot be reached with Tab or a screen reader.
  const away = (side: View) => (!wide && view !== side ? ({ inert: '', 'aria-hidden': true } as object) : {});

  const switchButton = (side: View, label: [string, string]) => (
    <button
      type="button"
      aria-pressed={view === side}
      aria-controls={`landing-${side}`}
      onClick={() => setView(side)}
      className={`relative z-10 flex-1 min-h-11 px-4 rounded-full text-sm font-semibold transition-colors ${
        view === side ? 'text-primary-foreground' : 'text-background/80 hover:text-background'
      }`}
    >
      {t(...label)}
    </button>
  );

  return (
    <div className="relative h-full overflow-hidden bg-background">
      <div
        className={`flex h-full w-[200%] lg:w-auto lg:grid lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] motion-safe:transition-transform motion-safe:duration-500 motion-safe:ease-out ${
          view === 'start' ? '-translate-x-1/2' : 'translate-x-0'
        } lg:translate-x-0`}
      >
        {/* ---------- Hero ---------- */}
        <section
          id="landing-hero"
          aria-labelledby="landing-title"
          {...away('hero')}
          className="relative isolate overflow-hidden w-1/2 lg:w-auto h-full rounded-b-[2rem] lg:rounded-bl-none lg:rounded-r-[4.5rem] bg-foreground text-white flex flex-col"
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
              <h1
                id="landing-title"
                className="text-4xl sm:text-5xl lg:text-[clamp(2.25rem,6.4vh,3.75rem)] font-bold font-title leading-[1.08] text-balance"
              >
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
          id="landing-start"
          aria-label={t('কীভাবে শুরু করবেন', 'How to start')}
          {...away('start')}
          className="w-1/2 lg:w-auto h-full min-w-0 overflow-y-auto flex flex-col gap-6 px-5 pt-6 pb-24 sm:px-9 sm:pt-8 lg:px-14 lg:py-[clamp(1.25rem,4vh,2.5rem)] lg:gap-[clamp(0.75rem,2.6vh,2rem)]"
        >
          <div className="flex justify-end">
            <PreferenceToggles />
          </div>

          <div className="flex-1 w-full max-w-md mx-auto flex flex-col justify-center gap-6 lg:gap-[clamp(0.75rem,2.8vh,2rem)]">
            <div className="flex flex-col gap-4 lg:gap-[clamp(0.625rem,1.8vh,1.25rem)]">
              <h2 className="text-2xl lg:text-[clamp(1.25rem,3vh,1.5rem)] font-bold font-title text-foreground">{t('অতিথি হিসেবে দেখুন', 'Explore as a guest')}</h2>
              <CapabilityList items={GUEST} />
              {member && (
                <p className="text-xs text-muted-foreground wrap-anywhere">
                  {t(`আপনি ${session.displayName} হিসেবে সাইন ইন আছেন; অতিথি হতে আগে সাইন আউট করতে হবে।`, `You are signed in as ${session.displayName}; guest mode needs you to sign out first.`)}
                </p>
              )}
              <Link to="/guest" className={buttonVariants({ size: 'lg', className: 'rounded-xl' })}>
                {t('অতিথি হিসেবে চালিয়ে যান', 'Continue as guest')}
                <ArrowRight size={16} aria-hidden="true" />
              </Link>
            </div>

            <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden="true">
              <span className="h-px flex-1 bg-border" />
              {t('অথবা', 'or')}
              <span className="h-px flex-1 bg-border" />
            </div>

            <div className="flex flex-col gap-4 lg:gap-[clamp(0.625rem,1.8vh,1.25rem)]">
              <h2 className="text-2xl lg:text-[clamp(1.25rem,3vh,1.5rem)] font-bold font-title text-foreground">{t('সদস্য হিসেবে সাইন ইন', 'Sign in as a member')}</h2>
              <CapabilityList items={MEMBER} />
              {member ? (
                <Link to="/overview" className={buttonVariants({ variant: 'outline', size: 'lg', className: 'rounded-xl' })}>
                  {t('অ্যাপে যান', 'Open the app')}
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
              ) : (
                <Link to="/login" className={buttonVariants({ variant: 'outline', size: 'lg', className: 'rounded-xl' })}>
                  <LogIn size={16} aria-hidden="true" />
                  {t('সাইন ইন', 'Sign in')}
                </Link>
              )}
            </div>
          </div>
        </section>
      </div>

      {/* Phone only: slides between the two sides. The green thumb marks the side on screen. */}
      <div
        role="group"
        aria-label={t('প্রথম পাতার অংশ', 'Front page sections')}
        className="lg:hidden absolute bottom-4 left-1/2 -translate-x-1/2 z-20 w-[min(20rem,calc(100%-2rem))] flex p-1 rounded-full bg-foreground/90 backdrop-blur shadow-[0_8px_24px_rgb(0_0_0/0.25)]"
      >
        <span
          aria-hidden="true"
          className={`absolute top-1 bottom-1 left-1 w-[calc(50%-0.25rem)] rounded-full bg-primary motion-safe:transition-transform motion-safe:duration-300 ${
            view === 'start' ? 'translate-x-full' : 'translate-x-0'
          }`}
        />
        {switchButton('hero', ['পরিচিতি', 'About'])}
        {switchButton('start', ['শুরু করুন', 'Get started'])}
      </div>
    </div>
  );
};
