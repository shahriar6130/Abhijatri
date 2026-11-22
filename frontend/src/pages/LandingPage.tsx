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
import { formatNumber } from '../utils/format';
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

/**
 * The front page (UI refresh, 22 Nov 2026), framed after the owner's reference: a photo hero of the
 * destinations on the left (brand, promise, photos that change by themselves), and on the right the
 * language and theme switches and the choice between guest and member. Stacked on small screens.
 */
export const LandingPage: React.FC = () => {
  const { language, t } = useLanguage();
  const { session } = useSession();
  const index = useAutoSlide(SLIDES.length);
  const [, image] = SLIDES[index] ?? [];
  const member = session.kind === 'member';
  const two = (n: number) => `${formatNumber(Math.floor(n / 10), language)}${formatNumber(n % 10, language)}`;

  return (
    // No outer frame (owner, 22 Nov 2026): the hero fills the left side edge to edge; the right side sits on the page.
    <div className="bg-background">
      <div className="lg:grid lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:min-h-screen">
        {/* ---------- Hero ---------- */}
        <section
          aria-labelledby="landing-title"
          className="relative isolate overflow-hidden min-h-[34rem] sm:min-h-[38rem] lg:min-h-0 lg:sticky lg:top-0 lg:h-screen rounded-b-[2.5rem] lg:rounded-bl-none lg:rounded-r-[4.5rem] bg-foreground text-white flex flex-col"
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
            </div>

            {image && (
              <div className="flex flex-col gap-2">
                {/* Shows where the slideshow is; not a control. */}
                <div className="flex items-center gap-4" aria-hidden="true">
                  <div className="flex gap-1.5 w-40 sm:w-56">
                    {SLIDES.map(([nameEn], i) => (
                      <span key={nameEn} className={`flex-1 h-0.5 rounded-full transition-colors ${i === index ? 'bg-white' : 'bg-white/35'}`} />
                    ))}
                  </div>
                  <span className="text-sm font-en tabular-nums">
                    <strong>{two(index + 1)}</strong>
                    <span className="text-white/70"> — {two(SLIDES.length)}</span>
                  </span>
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
        <section aria-label={t('কীভাবে শুরু করবেন', 'How to start')} className="min-w-0 flex flex-col gap-8 px-5 py-6 sm:px-9 sm:py-8 lg:px-14 lg:py-10">
          <div className="flex justify-end">
            <PreferenceToggles />
          </div>

          <div className="flex-1 w-full max-w-md mx-auto flex flex-col justify-center gap-8">
            <div className="flex flex-col gap-5">
              <h2 className="text-2xl font-bold font-title text-foreground">{t('অতিথি হিসেবে দেখুন', 'Explore as a guest')}</h2>
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

            <div className="flex flex-col gap-5">
              <h2 className="text-2xl font-bold font-title text-foreground">{t('সদস্য হিসেবে সাইন ইন', 'Sign in as a member')}</h2>
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
    </div>
  );
};
