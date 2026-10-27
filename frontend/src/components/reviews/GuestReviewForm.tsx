import React, { useEffect, useRef, useState } from 'react';
import { Send, ShieldCheck, Star } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import { ApiError } from '../../api/client';
import { getReviewParameters } from '../../api/reviewParameters';
import { useApiResource } from '../../hooks/useApiResource';
import {
  CATEGORY_RATINGS_ENABLED,
  buildGuestReviewPayload,
  detectReviewLanguage,
  generateReceipt,
  getGuestScopeSecret,
  submitGuestReview,
} from '../../api/reviews';
import type { CategoryRatings as Ratings, ComfortTier, DestinationSummary, GuestReviewCreated, ReviewLanguage, TravellerType } from '../../types';
import { currentDisplayMonth, pick } from '../../utils/format';
import { describeError } from '../common/StatusViews';
import { CategoryRatings } from './CategoryRatings';
import { ReviewPhotos, type ReviewPhoto } from './ReviewPhotos';
import { TURNSTILE_SITE_KEY, TurnstileWidget } from './TurnstileWidget';

/** Must match the API's expected Turnstile action (backend app/turnstile.py). */
const TURNSTILE_ACTION = 'guest-review';
import { COMFORT_TIERS, FIELD_ERROR_LABEL, REVIEW_LANGUAGES, TRAVELLER_TYPES } from './reviewLabels';

export interface SubmittedReview extends GuestReviewCreated {
  receipt: string;
  destinationId: string;
}

interface DraftIdentity {
  clientDraftId: string;
  receipt: string;
}

const newIdentity = (): DraftIdentity => ({ clientDraftId: crypto.randomUUID(), receipt: generateReceipt() });
/** Code-point length, which is how the server counts (Python len). */
const length = (value: string) => [...value.trim()].length;

const inputClass =
  'w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark aria-[invalid=true]:border-error-alert';
const labelClass = 'text-xs font-bold text-on-surface-variant dark:text-on-dark-muted';

export const GuestReviewForm: React.FC<{
  destinations: DestinationSummary[];
  initialDestinationId: string | null;
  onSubmitted: (review: SubmittedReview) => void;
}> = ({ destinations, initialDestinationId, onSubmitted }) => {
  const { language, t } = useLanguage();
  const { session } = useSession();
  const maxMonth = currentDisplayMonth();
  // Limits and category prompts come from the API (API.md 5.15); local values are the fallback.
  const { data: parameters } = useApiResource(() => getReviewParameters(), []);
  const noteMin = parameters?.note.min_length ?? 20;
  const noteMax = parameters?.note.max_length ?? 6000;
  const titleMin = parameters?.title.min_length ?? 3;
  const titleMax = parameters?.title.max_length ?? 160;
  const nameMax = parameters?.display_name.max_length ?? 80;

  const [destinationId, setDestinationId] = useState(
    initialDestinationId && destinations.some((d) => d.id === initialDestinationId) ? initialDestinationId : '',
  );
  // The name a guest gave on /guest pre-fills the public display name; it stays editable.
  const [displayName, setDisplayName] = useState(session.displayName ?? '');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  // A Turnstile token is single use: remount the widget after every attempt.
  const [turnstileKey, setTurnstileKey] = useState(0);
  // null until the reviewer picks a language; until then it follows the script they write in.
  const [chosenLanguage, setChosenLanguage] = useState<ReviewLanguage | null>(null);
  const [travellerType, setTravellerType] = useState<TravellerType>('SOLO');
  const [comfortTier, setComfortTier] = useState<ComfortTier>('STANDARD');
  const [visitMonth, setVisitMonth] = useState(maxMonth);
  const [rating, setRating] = useState(0);
  const [categoryRatings, setCategoryRatings] = useState<Ratings>({});
  const [photos, setPhotos] = useState<ReviewPhoto[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const detectedLanguage = detectReviewLanguage(`${title} ${body}`);
  const reviewLanguage: ReviewLanguage = chosenLanguage ?? detectedLanguage ?? (language === 'en' ? 'EN' : 'BN');
  const [consent, setConsent] = useState(false);
  // One identity per draft: every retry reuses it so the server can recover a lost response.
  const [identity, setIdentity] = useState<DraftIdentity>(newIdentity);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  // Bumped on every failed submit; the effect below then moves to the topmost error.
  const [errorFocusRequest, setErrorFocusRequest] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (errorFocusRequest === 0 || !formRef.current) return;
    // Error messages are `<p id="<field>-error">` or the form-level `role="alert"`;
    // querySelector returns the first match in document order, i.e. the topmost one.
    const message = formRef.current.querySelector<HTMLElement>('[id$="-error"], [role="alert"]');
    if (!message) return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    message.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
    // Focus the control the message describes (a radio group focuses its first option).
    const owner = message.id
      ? formRef.current.querySelector<HTMLElement>(`[aria-describedby~="${message.id}"]`)
      : null;
    const target = owner?.getAttribute('role') === 'radiogroup' ? owner.querySelector<HTMLElement>('[role="radio"]') : owner;
    if (target) {
      target.focus({ preventScroll: true });
    } else {
      // A form-level error has no field: focus the message so keyboard users land on it.
      message.tabIndex = -1;
      message.focus({ preventScroll: true });
    }
  }, [errorFocusRequest]);

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (!destinationId) errors.destination_id = t('একটি গন্তব্য বেছে নিন।', 'Choose a destination.');
    if (length(displayName) < 1 || length(displayName) > nameMax)
      errors.guest_display_name = t(
        `প্রদর্শন নাম ১ থেকে ${nameMax} অক্ষরের হতে হবে।`,
        `Display name must be 1 to ${nameMax} characters.`,
      );
    if (rating < 1) errors.overall_rating = t('১ থেকে ৫ তারকা দিন।', 'Give a rating from 1 to 5 stars.');
    if (!/^\d{4}-\d{2}$/.test(visitMonth) || visitMonth > maxMonth)
      errors.visit_month = t('ভ্রমণের মাস ভবিষ্যতের হতে পারবে না।', 'The visit month cannot be in the future.');
    if (length(title) < titleMin || length(title) > titleMax)
      errors.title = t(
        `শিরোনাম ${titleMin} থেকে ${titleMax} অক্ষরের হতে হবে।`,
        `Title must be ${titleMin} to ${titleMax} characters.`,
      );
    if (length(body) < noteMin || length(body) > noteMax)
      errors.body = t(
        `নোট আবশ্যক: ${noteMin} থেকে ${noteMax} অক্ষর লিখুন।`,
        `A note is required: write ${noteMin} to ${noteMax} characters.`,
      );
    if (!consent) errors.consent = t('জমা দেওয়ার আগে নোটিশে সম্মতি দিন।', 'Agree to the notice before submitting.');
    if (TURNSTILE_SITE_KEY && !turnstileToken)
      errors.turnstile = t('নিরাপত্তা যাচাইটি সম্পন্ন করুন।', 'Complete the security check.');
    return errors;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setErrorFocusRequest((n) => n + 1);
      return;
    }

    setSubmitting(true);
    try {
      const created = await submitGuestReview({
        ...buildGuestReviewPayload({
          destinationId,
          clientDraftId: identity.clientDraftId,
          receipt: identity.receipt,
          guestScopeSecret: getGuestScopeSecret(),
          displayName,
          language: reviewLanguage,
          travellerType,
          comfortTier,
          visitMonth,
          title,
          note: body,
          overallRating: rating,
          categoryRatings,
        }),
        ...(turnstileToken ? { turnstile_token: turnstileToken } : {}),
      });
      onSubmitted({ ...created, receipt: identity.receipt, destinationId });
      setIdentity(newIdentity());
      setTitle('');
      setBody('');
      setRating(0);
      setCategoryRatings({});
      setPhotos([]);
      setChosenLanguage(null);
      setConsent(false);
    } catch (error: unknown) {
      if (error instanceof ApiError) {
        if (error.fieldErrors.length > 0) {
          const mapped: Record<string, string> = {};
          error.fieldErrors.forEach(({ field, code }) => {
            mapped[field] = t(...(FIELD_ERROR_LABEL[code] ?? FIELD_ERROR_LABEL.INVALID_VALUE));
          });
          setFieldErrors(mapped);
        }
        if (error.code === 'RESERVED_DISPLAY_NAME') {
          setFieldErrors({ guest_display_name: error.message });
        }
        if (error.code === 'DRAFT_ALREADY_SUBMITTED') {
          setIdentity(newIdentity()); // this draft identity is spent; start a fresh one
        }
      }
      setFormError(describeError(error, t));
      setErrorFocusRequest((n) => n + 1);
    } finally {
      setSubmitting(false);
      setTurnstileKey((n) => n + 1);
    }
  };

  const errorFor = (field: string) =>
    fieldErrors[field] ? (
      <p id={`${field}-error`} className="text-xs text-error-alert dark:text-red-400">
        {fieldErrors[field]}
      </p>
    ) : null;
  const describedBy = (field: string) => (fieldErrors[field] ? `${field}-error` : undefined);

  return (
    <form ref={formRef} onSubmit={handleSubmit} noValidate className="tonal-card p-6 flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="review-destination" className={labelClass}>
          {t('গন্তব্য', 'Destination')}
        </label>
        <select
          id="review-destination"
          value={destinationId}
          onChange={(e) => setDestinationId(e.target.value)}
          aria-invalid={Boolean(fieldErrors.destination_id)}
          aria-describedby={describedBy('destination_id')}
          className={inputClass}
        >
          <option value="">{t('বেছে নিন…', 'Choose…')}</option>
          {destinations.map((d) => (
            <option key={d.id} value={d.id}>
              {pick(language, d.name_bn, d.name_en)}
            </option>
          ))}
        </select>
        {errorFor('destination_id')}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="review-name" className={labelClass}>
            {t('আপনার নাম (শুধু মডারেটর দেখবেন; প্রকাশ্যে "বেনামী অতিথি" দেখাবে)', 'Your name (seen only by moderators; shown publicly as "Anonymous guest")')}
          </label>
          <input
            id="review-name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={nameMax}
            autoComplete="nickname"
            aria-invalid={Boolean(fieldErrors.guest_display_name)}
            aria-describedby={describedBy('guest_display_name')}
            className={inputClass}
          />
          {errorFor('guest_display_name')}
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="review-month" className={labelClass}>
            {t('ভ্রমণের মাস', 'Month of visit')}
          </label>
          <input
            id="review-month"
            type="month"
            value={visitMonth}
            max={maxMonth}
            onChange={(e) => setVisitMonth(e.target.value)}
            aria-invalid={Boolean(fieldErrors.visit_month)}
            aria-describedby={describedBy('visit_month')}
            className={`${inputClass} font-en`}
          />
          {errorFor('visit_month')}
        </div>
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className={labelClass}>{t('সার্বিক রেটিং', 'Overall rating')}</legend>
        <div className="flex items-center gap-1" role="radiogroup" aria-describedby={describedBy('overall_rating')}>
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              role="radio"
              aria-checked={rating === star}
              aria-label={t(`${star} তারকা`, `${star} star${star === 1 ? '' : 's'}`)}
              onClick={() => setRating(star)}
              className="p-1.5 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full"
            >
              <Star
                size={26}
                aria-hidden="true"
                className={star <= rating ? 'fill-amber-400 text-amber-400' : 'text-surface-muted dark:text-on-dark-muted'}
              />
            </button>
          ))}
        </div>
        {errorFor('overall_rating')}
      </fieldset>

      <CategoryRatings
        value={categoryRatings}
        onChange={setCategoryRatings}
        pendingServerSupport={!CATEGORY_RATINGS_ENABLED}
        categories={parameters?.categories}
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="review-traveller" className={labelClass}>
            {t('ভ্রমণকারীর ধরন', 'Traveller type')}
          </label>
          <select id="review-traveller" value={travellerType} onChange={(e) => setTravellerType(e.target.value as TravellerType)} className={inputClass}>
            {TRAVELLER_TYPES.map(([value, label]) => (
              <option key={value} value={value}>
                {t(...label)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="review-comfort" className={labelClass}>
            {t('খরচের ধরন', 'Comfort tier')}
          </label>
          <select id="review-comfort" value={comfortTier} onChange={(e) => setComfortTier(e.target.value as ComfortTier)} className={inputClass}>
            {COMFORT_TIERS.map(([value, label]) => (
              <option key={value} value={value}>
                {t(...label)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="review-language" className={labelClass}>
            {t('রিভিউয়ের ভাষা', 'Review language')}
          </label>
          <select
            id="review-language"
            value={reviewLanguage}
            onChange={(e) => setChosenLanguage(e.target.value as ReviewLanguage)}
            aria-describedby="review-language-hint"
            className={inputClass}
          >
            {REVIEW_LANGUAGES.map(([value, label]) => (
              <option key={value} value={value}>
                {t(...label)}
              </option>
            ))}
          </select>
          <p id="review-language-hint" className="text-[11px] text-on-surface-variant dark:text-on-dark-muted">
            {chosenLanguage
              ? t('আপনার বেছে নেওয়া ভাষা', 'Chosen by you')
              : detectedLanguage
                ? t('আপনার লেখা থেকে শনাক্ত করা', 'Detected from your writing')
                : t('লেখা শুরু করলে শনাক্ত হবে', 'Detected once you start writing')}
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="review-title" className={labelClass}>
          {t('শিরোনাম', 'Title')}
        </label>
        <input
          id="review-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={titleMax}
          aria-invalid={Boolean(fieldErrors.title)}
          aria-describedby={describedBy('title')}
          className={inputClass}
        />
        {errorFor('title')}
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="review-body" className={labelClass}>
          {t('আপনার নোট (আবশ্যক)', 'Your note (required)')}
        </label>
        <textarea
          id="review-body"
          rows={6}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={noteMax}
          required
          aria-required="true"
          placeholder={t(
            'যাতায়াত, থাকা, খাবার, খরচ ও সতর্কতা নিয়ে লিখুন। ফোন নম্বর বা অন্যের ব্যক্তিগত তথ্য দেবেন না।',
            'Write about transport, stay, food, costs and cautions. Do not include phone numbers or anyone’s personal details.',
          )}
          aria-invalid={Boolean(fieldErrors.body)}
          aria-describedby={`body-count${fieldErrors.body ? ' body-error' : ''}`}
          className={`${inputClass} py-3 font-body`}
        />
        <p id="body-count" className="text-[11px] text-on-surface-variant dark:text-on-dark-muted font-en">
          {length(body)} / {noteMax}{' '}
          {length(body) < noteMin && t(`(কমপক্ষে ${noteMin})`, `(at least ${noteMin})`)}
        </p>
        {errorFor('body')}
      </div>

      <ReviewPhotos photos={photos} onChange={setPhotos} />

      <div className="p-4 rounded-xl bg-surface-container/60 dark:bg-dark-surface-2 flex flex-col gap-3 text-xs text-on-surface-variant dark:text-on-dark-muted">
        <p className="flex gap-2">
          <ShieldCheck size={16} className="text-forest-primary dark:text-neon-lime shrink-0" aria-hidden="true" />
          <span>
            {t(
              'আপনার রিভিউ একজন মডারেটর পড়ার পর প্রকাশিত হবে "বেনামী অতিথি" হিসেবে। এই ব্রাউজার থেকে দেওয়া আপনার সব রিভিউতে একই অতিথি ট্যাগ দেখানো হবে, যাতে পাঠকরা বুঝতে পারেন সেগুলো একই অতিথির। অতিথি রেটিং শুধু আলাদা "অতিথি মতামত"-এ গণনা হয়। জমা দেওয়ার পর একটি রিসিপ্ট একবারই দেখানো হবে; সেটি দিয়ে অবস্থা দেখা ও প্রত্যাহার করা যাবে। হারানো রিসিপ্ট পুনরুদ্ধার করা যায় না।',
              'A moderator reads your review before it is published as "Anonymous guest". Your reviews from this browser show the same guest tag, so readers can see they came from the same guest. Guest ratings count only towards the separate Guest Feedback. After submitting you see a receipt once; it lets you check status and withdraw. A lost receipt cannot be recovered.',
            )}
          </span>
        </p>
        <label className="flex items-start gap-2 min-h-[44px] cursor-pointer text-on-surface dark:text-on-dark">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            aria-describedby={describedBy('consent')}
            className="mt-0.5 h-5 w-5 accent-forest-primary dark:accent-neon-lime"
          />
          <span>{t('আমি নোটিশটি পড়েছি এবং সম্মতি দিচ্ছি।', 'I have read the notice and agree.')}</span>
        </label>
        {errorFor('consent')}
      </div>

      {TURNSTILE_SITE_KEY && (
        <div aria-describedby={describedBy('turnstile')}>
          <TurnstileWidget key={turnstileKey} action={TURNSTILE_ACTION} onToken={setTurnstileToken} />
          {errorFor('turnstile')}
        </div>
      )}

      {formError && (
        <p role="alert" className="p-3 rounded-xl bg-error-container text-sm text-red-900 dark:bg-red-950/40 dark:text-red-200">
          {formError}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="self-start inline-flex items-center gap-2 min-h-[44px] px-6 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title disabled:opacity-60"
      >
        <Send size={16} aria-hidden="true" />
        {submitting ? t('জমা হচ্ছে…', 'Submitting…') : t('রিভিউ জমা দিন', 'Submit review')}
      </button>
    </form>
  );
};
