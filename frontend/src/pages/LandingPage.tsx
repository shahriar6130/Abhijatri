import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Compass,
  ImagePlus,
  LogIn,
  MapPin,
  MessageSquareText,
  Pause,
  Phone,
  Play,
  Search,
  ShieldAlert,
  UserRound,
} from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { useDestinationCatalog } from '../hooks/useDestinationCatalog';
import { EmptyState, ErrorState } from '../components/common/StatusViews';
import { ImageCredit } from '../components/common/ImageCredit';
import { LandingMenu } from '../components/layout/LandingMenu';
import { PreferenceToggles } from '../components/layout/PreferenceToggles';
import { allDestinationImages, destinationImage, type DestinationImage } from '../data/destinationImages';
import type { DestinationSummary } from '../types';
import { formatNumber, pick } from '../utils/format';
import { buttonVariants } from '@/components/ui/button';

/** Seconds each hero photo stays before the next one (paused by the button, hover, focus or reduced motion). */
const SLIDE_SECONDS = 7;

type Landscape = 'HILLS' | 'SEA' | 'FOREST' | 'TEA';
type Tab = Landscape | 'ALL';

/**
 * Landscape of each seeded destination, for the tabs. The API has no such field yet, so it is set
 * here by English name (record ids differ between databases); a new destination appears under All
 * only until it is added here (Decisions 2026-11-22).
 */
const LANDSCAPE: Record<string, Landscape> = {
  Bandarban: 'HILLS',
  'Sajek Valley': 'HILLS',
  "Cox's Bazar": 'SEA',
  Sundarbans: 'FOREST',
  Sylhet: 'TEA',
};
const TABS: { id: Tab; label: [string, string] }[] = [
  { id: 'ALL', label: ['সব', 'All'] },
  { id: 'HILLS', label: ['পাহাড়', 'Hills'] },
  { id: 'SEA', label: ['সমুদ্র', 'Sea'] },
  { id: 'FOREST', label: ['বন', 'Forest'] },
  { id: 'TEA', label: ['চা-বাগান', 'Tea gardens'] },
];

/** A hero slide: a photo, and the destination it belongs to when the list has loaded. */
interface Slide {
  key: string;
  name: string;
  image: DestinationImage;
  destination: DestinationSummary | null;
}

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
    <ul className="flex flex-col gap-3">
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

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * The front page (UI refresh, 22 Nov 2026), framed after the owner's reference: a photo hero of the
 * destinations on the left with the brand, the promise and the entry buttons; on the right a
 * greeting, a destination search, landscape tabs and destination cards. Stacked on small screens.
 */
export const LandingPage: React.FC = () => {
  const { language, t } = useLanguage();
  const { session } = useSession();
  const navigate = useNavigate();
  // Optional: the page works if this request fails. Offline it lists only destinations saved on this device.
  const { data: catalog, loading, error, reload } = useDestinationCatalog();
  const destinations = catalog?.items ?? null;

  // Hero slides: the destinations that have a licensed photo, or the photos alone until the list loads.
  const slides = useMemo<Slide[]>(() => {
    const fromList = (destinations ?? []).flatMap((d) => {
      const image = destinationImage(d.name_en);
      return image ? [{ key: d.id, name: pick(language, d.name_bn, d.name_en), image, destination: d }] : [];
    });
    if (fromList.length > 0) return fromList;
    return allDestinationImages().map(([nameEn, image]) => ({ key: nameEn, name: image.place[language], image, destination: null }));
  }, [destinations, language]);

  const [current, setCurrent] = useState(0);
  const [paused, setPaused] = useState(prefersReducedMotion);
  const [holding, setHolding] = useState(false); // pointer or focus inside the page frame
  const index = slides.length > 0 ? current % slides.length : 0;
  const slide = slides[index];

  useEffect(() => {
    if (paused || holding || slides.length < 2) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setCurrent((n) => (n + 1) % slides.length);
    }, SLIDE_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [paused, holding, slides.length]);

  const show = useCallback(
    (key: string) => {
      const at = slides.findIndex((s) => s.key === key);
      if (at >= 0) setCurrent(at);
    },
    [slides],
  );

  const [tab, setTab] = useState<Tab>('ALL');
  const present = useMemo(
    () => new Set((destinations ?? []).map((d) => LANDSCAPE[d.name_en]).filter(Boolean)),
    [destinations],
  );
  const tabs = TABS.filter((x) => x.id === 'ALL' || present.has(x.id));
  const activeTab: Tab = tabs.some((x) => x.id === tab) ? tab : 'ALL';
  const cards = (destinations ?? []).filter((d) => activeTab === 'ALL' || LANDSCAPE[d.name_en] === activeTab);

  const [query, setQuery] = useState('');
  const search = (event: React.FormEvent) => {
    event.preventDefault();
    const q = query.trim();
    navigate(q ? `/destinations?q=${encodeURIComponent(q)}` : '/destinations');
  };

  const two = (n: number) => `${formatNumber(Math.floor(n / 10), language)}${formatNumber(n % 10, language)}`;
  const greetingName = session.displayName;
  const member = session.kind === 'member';

  return (
    <div className="bg-surface-sage dark:bg-background px-3 py-3 sm:px-5 sm:py-5">
      <div
        className="max-w-[1400px] mx-auto bg-card rounded-[2rem] shadow-[0_24px_64px_rgb(0_0_0/0.08)] dark:shadow-none dark:border dark:border-border overflow-hidden lg:grid lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:min-h-[min(880px,calc(100vh-2.5rem))]"
        onPointerEnter={() => setHolding(true)}
        onPointerLeave={() => setHolding(false)}
        onFocus={() => setHolding(true)}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHolding(false);
        }}
      >
        {/* ---------- Hero ---------- */}
        <section
          aria-labelledby="landing-title"
          className="relative isolate overflow-hidden min-h-[36rem] sm:min-h-[40rem] lg:min-h-0 rounded-b-[2.5rem] lg:rounded-bl-none lg:rounded-r-[4.5rem] bg-foreground text-white flex flex-col"
        >
          {slides.map((s, i) => {
            // Keep the previous, current and next photo in the page: the next one loads before it fades in.
            const near = i === index || i === (index + 1) % slides.length || i === (index - 1 + slides.length) % slides.length;
            if (!near) return null;
            return (
              <img
                key={s.key}
                src={s.image.src}
                srcSet={`${s.image.srcSmall} 480w, ${s.image.src} 1024w`}
                sizes="(min-width: 1024px) 58vw, 100vw"
                width={s.image.width}
                height={s.image.height}
                alt={i === index ? s.image.alt[language] : ''}
                aria-hidden={i === index ? undefined : true}
                fetchPriority={i === index ? 'high' : 'low'}
                className={`absolute inset-0 -z-20 h-full w-full object-cover motion-safe:transition-opacity motion-safe:duration-1000 ${i === index ? 'opacity-100' : 'opacity-0'}`}
              />
            );
          })}
          {/* Darkens the photo where the text sits, so white text keeps its contrast on any image. */}
          <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-t from-black/85 via-black/35 to-black/40" />
          <div aria-hidden="true" className="absolute inset-0 -z-10 bg-gradient-to-r from-black/45 to-transparent" />

          <div className="flex-1 flex flex-col p-7 sm:p-10 lg:p-14 gap-8">
            <Link to="/" className="self-start inline-flex items-center gap-3 min-h-11" aria-label={t('অভিযাত্রী হোম', 'Abhijatri home')}>
              <span className="w-10 h-10 rounded-full border-2 border-white/90 flex items-center justify-center">
                <Compass size={20} aria-hidden="true" />
              </span>
              <span className="font-title text-xl font-bold">অভিযাত্রী</span>
            </Link>

            <div className="mt-auto flex flex-col gap-5 max-w-xl">
              <h1 id="landing-title" className="text-4xl sm:text-5xl lg:text-6xl font-bold font-title leading-[1.08] text-balance">
                {t('যাওয়ার আগে জানুন, ফিরে এসে জানান', 'Know before you go. Share when you are back.')}
              </h1>
              <p className="text-base sm:text-lg leading-relaxed text-white/85 max-w-lg">
                {t(
                  'সূত্র ও তারিখসহ গন্তব্য গাইড, নিরাপত্তা সতর্কতা, জরুরি নম্বর আর মডারেশন করা ভ্রমণকারীর রিভিউ, বাংলায় ও ইংরেজিতে।',
                  'Source-dated destination guides, safety advisories, emergency numbers and moderated traveller reviews, in Bangla and English.',
                )}
              </p>
              <div className="flex flex-wrap gap-3 pt-1">
                {member ? (
                  <Link to="/overview" className={buttonVariants({ size: 'lg', className: 'rounded-xl px-7' })}>
                    {t('অ্যাপে যান', 'Open the app')}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                ) : (
                  <>
                    <Link to="/guest" className={buttonVariants({ size: 'lg', className: 'rounded-xl px-7' })}>
                      {t('অতিথি হিসেবে শুরু করুন', 'Start as a guest')}
                      <ArrowRight size={16} aria-hidden="true" />
                    </Link>
                    <Link
                      to="/login"
                      className="inline-flex items-center justify-center gap-2 min-h-12 px-6 rounded-xl border border-white/60 text-white text-base font-semibold hover:bg-white/10"
                    >
                      <LogIn size={16} aria-hidden="true" />
                      {t('সাইন ইন', 'Sign in')}
                    </Link>
                  </>
                )}
              </div>
            </div>

            {slide && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-4">
                  {/* One segment per photo: a segment is also a way to jump to that photo. */}
                  <div className="flex gap-1.5 w-40 sm:w-56" role="group" aria-label={t('ছবি বেছে নিন', 'Choose a photo')}>
                    {slides.map((s, i) => (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => setCurrent(i)}
                        aria-label={s.name}
                        aria-current={i === index ? 'true' : undefined}
                        className="group flex-1 py-3 -my-3"
                      >
                        <span className={`block h-0.5 rounded-full transition-colors ${i === index ? 'bg-white' : 'bg-white/35 group-hover:bg-white/70'}`} />
                      </button>
                    ))}
                  </div>
                  <span className="text-sm font-en tabular-nums" aria-hidden="true">
                    <strong>{two(index + 1)}</strong>
                    <span className="text-white/70"> — {two(slides.length)}</span>
                  </span>
                  {slides.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setPaused((p) => !p)}
                      aria-pressed={paused}
                      aria-label={paused ? t('ছবি চালান', 'Play photos') : t('ছবি থামান', 'Pause photos')}
                      className="ml-auto w-11 h-11 rounded-full border border-white/40 flex items-center justify-center hover:bg-white/10"
                    >
                      {paused ? <Play size={15} aria-hidden="true" /> : <Pause size={15} aria-hidden="true" />}
                    </button>
                  )}
                </div>
                <p className="text-sm font-semibold">
                  {slide.destination ? (
                    <Link to={`/destinations/${slide.destination.id}`} className="inline-flex items-center gap-1.5 min-h-11 hover:underline underline-offset-4">
                      <MapPin size={14} aria-hidden="true" />
                      {slide.name}
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 min-h-11">
                      <MapPin size={14} aria-hidden="true" />
                      {slide.name}
                    </span>
                  )}
                </p>
                <p className="text-[11px] text-white/70">
                  <ImageCredit credit={slide.image.credit} />
                </p>
              </div>
            )}
          </div>
        </section>

        {/* ---------- Discover panel ---------- */}
        <section aria-labelledby="landing-discover" className="min-w-0 flex flex-col gap-7 p-6 sm:p-9 lg:p-12">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <LandingMenu />
            <div className="flex items-center gap-3 flex-wrap justify-end">
              <PreferenceToggles />
              <span className="inline-flex items-center gap-2.5 text-sm text-foreground">
                <span className="hidden sm:inline">
                  {greetingName ? t(`স্বাগতম, ${greetingName}`, `Hi, ${greetingName}`) : t('স্বাগতম', 'Welcome')}
                </span>
                <span
                  aria-hidden="true"
                  className="w-10 h-10 rounded-full bg-foreground text-background flex items-center justify-center font-semibold"
                >
                  {greetingName ? [...greetingName.trim()][0]?.toLocaleUpperCase() : <UserRound size={18} />}
                </span>
              </span>
            </div>
          </div>

          <form role="search" onSubmit={search} className="relative">
            <label htmlFor="landing-search" className="sr-only">{t('গন্তব্য খুঁজুন', 'Search destinations')}</label>
            <input
              id="landing-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('যেমন "কক্সবাজার"', 'Try "Cox\'s Bazar"')}
              className="w-full min-h-14 pl-5 pr-14 rounded-2xl bg-card border border-border shadow-[0_8px_24px_rgb(0_0_0/0.06)] dark:shadow-none text-base text-foreground placeholder:text-muted-foreground"
            />
            <button
              type="submit"
              aria-label={t('খুঁজুন', 'Search')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 w-11 h-11 rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground"
            >
              <Search size={20} aria-hidden="true" />
            </button>
          </form>

          <div className="flex flex-col gap-4">
            <h2 id="landing-discover" className="text-3xl sm:text-4xl font-bold font-title text-foreground">
              {t('নতুন জায়গা খুঁজুন', 'Discover new')}
            </h2>
            {destinations && destinations.length > 0 && (
              <div role="tablist" aria-label={t('ভূপ্রকৃতি', 'Landscape')} className="flex flex-wrap gap-x-6 gap-y-1">
                {tabs.map((x) => {
                  const selected = x.id === activeTab;
                  return (
                    <button
                      key={x.id}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      aria-controls="landing-cards"
                      onClick={() => setTab(x.id)}
                      className={`min-h-11 text-base border-b-2 transition-colors ${
                        selected ? 'text-foreground font-semibold border-foreground' : 'text-muted-foreground border-transparent hover:text-foreground'
                      }`}
                    >
                      {t(...x.label)}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {loading && (
            <div role="status" aria-busy="true" className="flex gap-4 overflow-hidden">
              <span className="sr-only">{t('গন্তব্য লোড হচ্ছে…', 'Loading destinations…')}</span>
              {[0, 1, 2].map((n) => (
                <div key={n} className="w-44 shrink-0 h-64 rounded-2xl bg-muted motion-safe:animate-pulse" />
              ))}
            </div>
          )}
          {!loading && error != null && <ErrorState error={error} onRetry={reload} />}
          {!loading && !error && destinations && destinations.length === 0 && (
            <EmptyState
              title={catalog?.saved ? t('এই ডিভাইসে কোনো গন্তব্য সংরক্ষিত নেই', 'No destinations saved on this device') : t('এখনো কোনো প্রকাশিত গন্তব্য নেই', 'No published destinations yet')}
            />
          )}

          {cards.length > 0 && (
            <div className="flex flex-col gap-3">
              {catalog?.saved && (
                <p className="text-xs text-muted-foreground">
                  {t('অফলাইন: শুধু এই ডিভাইসে সংরক্ষিত গন্তব্য দেখানো হচ্ছে।', 'Offline: only destinations saved on this device are shown.')}
                </p>
              )}
              <ul
                id="landing-cards"
                role="tabpanel"
                aria-label={t(...(tabs.find((x) => x.id === activeTab) ?? TABS[0]).label)}
                className="flex gap-4 overflow-x-auto snap-x snap-mandatory pt-2 pb-10 -mb-6 -mx-3 px-3"
              >
                {cards.map((d) => {
                  const image = destinationImage(d.name_en);
                  const selected = slide?.destination?.id === d.id;
                  return (
                    <li key={d.id} className="snap-start shrink-0 w-44 sm:w-48">
                      <Link
                        to={`/destinations/${d.id}`}
                        onPointerEnter={() => show(d.id)}
                        onFocus={() => show(d.id)}
                        className={`group h-full flex flex-col gap-2 p-1.5 rounded-2xl bg-card border transition-shadow ${
                          selected ? 'border-transparent shadow-[0_12px_32px_rgb(0_0_0/0.14)] dark:border-border' : 'border-border hover:shadow-[0_8px_24px_rgb(0_0_0/0.10)]'
                        }`}
                      >
                        {image ? (
                          <img
                            src={image.srcSmall}
                            width={480}
                            height={Math.round((480 * image.height) / image.width)}
                            alt=""
                            loading="lazy"
                            className="aspect-square w-full rounded-xl object-cover"
                          />
                        ) : (
                          <span aria-hidden="true" className="aspect-square w-full rounded-xl bg-muted flex items-center justify-center text-muted-foreground">
                            <MapPin size={24} />
                          </span>
                        )}
                        <span className="px-1.5 flex flex-col gap-0.5">
                          <span className="font-medium text-foreground">{pick(language, d.name_bn, d.name_en)}</span>
                          <span className="text-xs text-muted-foreground line-clamp-1">{pick(language, d.region_bn, d.region_en)}</span>
                          {d.active_advisory_count > 0 && (
                            <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-amber-800 dark:text-amber-300">
                              <AlertTriangle size={12} aria-hidden="true" />
                              {formatNumber(d.active_advisory_count, language)} {t('সতর্কতা', d.active_advisory_count === 1 ? 'advisory' : 'advisories')}
                            </span>
                          )}
                        </span>
                        <span
                          className={`mt-auto ${buttonVariants({ size: 'sm', className: 'w-full rounded-xl pointer-events-none' })} ${
                            selected ? '' : 'invisible group-hover:visible group-focus-visible:visible'
                          }`}
                        >
                          {t('গাইড দেখুন', 'Open guide')}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link to="/destinations" className="inline-flex items-center gap-1.5 min-h-11 text-sm font-semibold text-foreground hover:underline underline-offset-4">
                  {t('সব গন্তব্য দেখুন', 'See all destinations')}
                  <ArrowRight size={14} aria-hidden="true" />
                </Link>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer min-h-11 inline-flex items-center">{t('ছবির সূত্র', 'Photo credits')}</summary>
                  <ul className="flex flex-col gap-1 pt-1">
                    {allDestinationImages().map(([nameEn, image]) => (
                      <li key={nameEn}>
                        {image.place[language]}: <ImageCredit credit={image.credit} />
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* ---------- Guest or member ---------- */}
      <section aria-label={t('কীভাবে শুরু করবেন', 'How to start')} className="max-w-[1400px] mx-auto grid grid-cols-1 md:grid-cols-2 gap-5 mt-5">
        <article className="bg-card rounded-[2rem] border border-border p-7 sm:p-9 flex flex-col gap-5">
          <div className="flex flex-col gap-1">
            <h2 className="text-xl font-bold font-title text-foreground">{t('অতিথি হিসেবে দেখুন', 'Explore as a guest')}</h2>
            <p className="text-sm text-muted-foreground">{t('কোনো অ্যাকাউন্ট বা ব্যক্তিগত তথ্য লাগবে না।', 'No account and no personal details needed.')}</p>
          </div>
          <CapabilityList items={GUEST} />
          {member && (
            <p className="text-xs text-muted-foreground wrap-anywhere">
              {t(`আপনি ${session.displayName} হিসেবে সাইন ইন আছেন; অতিথি হতে আগে সাইন আউট করতে হবে।`, `You are signed in as ${session.displayName}; guest mode needs you to sign out first.`)}
            </p>
          )}
          <Link to="/guest" className={buttonVariants({ size: 'lg', className: 'mt-auto rounded-xl' })}>
            {t('অতিথি হিসেবে চালিয়ে যান', 'Continue as guest')}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </article>

        <article className="bg-card rounded-[2rem] border border-border p-7 sm:p-9 flex flex-col gap-5">
          <div className="flex flex-col gap-1">
            <h2 className="text-xl font-bold font-title text-foreground">{t('সদস্য হিসেবে সাইন ইন', 'Sign in as a member')}</h2>
            <p className="text-sm text-muted-foreground">{t('অতিথির সব সুবিধা, সাথে আরও কিছু।', 'Everything a guest can do, and more.')}</p>
          </div>
          <CapabilityList items={MEMBER} />
          <Link to="/login" className={buttonVariants({ variant: 'outline', size: 'lg', className: 'mt-auto rounded-xl' })}>
            <LogIn size={16} aria-hidden="true" />
            {t('সাইন ইন', 'Sign in')}
          </Link>
        </article>
      </section>
    </div>
  );
};

