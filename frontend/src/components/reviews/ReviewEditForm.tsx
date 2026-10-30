import React, { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Save, Star } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { ApiError } from '../../api/client';
import { getReviewParameters } from '../../api/reviewParameters';
import { useApiResource } from '../../hooks/useApiResource';
import type { ComfortTier, ReviewEditChanges, ReviewLanguage, TravellerType } from '../../types';
import { currentDisplayMonth } from '../../utils/format';
import { codePoints, diffEdit, hasChanges, type EditableValues } from '../../utils/reviewAuthor';
import { describeError } from '../common/StatusViews';
import { CategoryRatings } from './CategoryRatings';
import { COMFORT_TIERS, FIELD_ERROR_LABEL, REVIEW_LANGUAGES, TRAVELLER_TYPES } from './reviewLabels';

const inputClass =
  'w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark aria-[invalid=true]:border-error-alert';
const labelClass = 'text-xs font-bold text-on-surface-variant dark:text-on-dark-muted';

type Field = 'title' | 'body' | 'overallRating' | 'visitMonth' | 'language' | 'travellerType' | 'comfortTier' | 'categoryRatings';

/**
 * Edit a review that is not published yet (API.md 5.5). One component, two callers:
 *  - a Member: `original` is the review as the server holds it; only fields that differ are sent;
 *  - a Guest: the review cannot be read back, so the form starts empty and only fields the guest
 *    touched are sent ("fill in only what you want to change").
 * Every save creates a new revision and sends the review back to the moderators.
 */
export const ReviewEditForm: React.FC<{
  mode: 'member' | 'guest';
  original: EditableValues;
  onSave: (changes: ReviewEditChanges) => Promise<void>;
  onCancel: () => void;
  /** Called after a version conflict so the page can reload the latest version. */
  onReload?: () => void;
  /** Shown above the form, for example the moderator's reason. */
  intro?: React.ReactNode;
}> = ({ mode, original, onSave, onCancel, onReload, intro }) => {
  const { t } = useLanguage();
  const guest = mode === 'guest';
  const maxMonth = currentDisplayMonth();
  const { data: parameters } = useApiResource(() => getReviewParameters(), []);
  const titleMin = parameters?.title.min_length ?? 3;
  const titleMax = parameters?.title.max_length ?? 160;
  const noteMin = parameters?.note.min_length ?? 20;
  const noteMax = parameters?.note.max_length ?? 6000;

  const [values, setValues] = useState<EditableValues>(original);
  const [touched, setTouched] = useState<Set<Field>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [locked, setLocked] = useState(false);
  const [saving, setSaving] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const [focusRequest, setFocusRequest] = useState(0);

  // A reload (after a conflict) hands in a new original: start again from it.
  useEffect(() => {
    setValues(original);
    setTouched(new Set());
    setConflict(false);
    setFieldErrors({});
    setFormError(null);
  }, [original]);

  useEffect(() => {
    if (focusRequest === 0 || !formRef.current) return;
    const first = formRef.current.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (first) first.focus();
    else formRef.current.querySelector<HTMLElement>('[role="alert"]')?.focus();
  }, [focusRequest]);

  const set = <K extends keyof EditableValues>(field: K, value: EditableValues[K]) => {
    setValues((prev) => ({ ...prev, [field]: value }));
    setTouched((prev) => new Set(prev).add(field));
    setFieldErrors((prev) => {
      if (!(field in prev) && !(snake(field) in prev)) return prev;
      const next = { ...prev };
      delete next[field];
      delete next[snake(field)];
      return next;
    });
  };

  const changes = useMemo<ReviewEditChanges>(() => {
    if (!guest) return diffEdit(original, values);
    // A guest's untouched fields stay out of the request; touched ones are sent as typed.
    const only: ReviewEditChanges = {};
    const clean = (v: string) => v.trim().normalize('NFC');
    if (touched.has('title')) only.title = clean(values.title);
    if (touched.has('body')) only.body = clean(values.body);
    if (touched.has('overallRating') && values.overallRating > 0) only.overall_rating = values.overallRating;
    if (touched.has('visitMonth')) only.visit_month = `${values.visitMonth}-01`;
    if (touched.has('language')) only.language = values.language;
    if (touched.has('travellerType')) only.traveller_type = values.travellerType;
    if (touched.has('comfortTier')) only.comfort_tier = values.comfortTier;
    if (touched.has('categoryRatings')) only.category_ratings = Object.fromEntries(Object.entries(values.categoryRatings).filter(([, v]) => Number.isInteger(v)));
    return only;
  }, [guest, original, values, touched]);

  const changed = hasChanges(changes);

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {};
    if ('title' in changes && (codePoints(changes.title ?? '') < titleMin || codePoints(changes.title ?? '') > titleMax))
      errors.title = t(`শিরোনাম ${titleMin} থেকে ${titleMax} অক্ষরের হতে হবে।`, `Title must be ${titleMin} to ${titleMax} characters.`);
    if ('body' in changes && (codePoints(changes.body ?? '') < noteMin || codePoints(changes.body ?? '') > noteMax))
      errors.body = t(`নোট ${noteMin} থেকে ${noteMax} অক্ষরের হতে হবে।`, `The note must be ${noteMin} to ${noteMax} characters.`);
    if ('visit_month' in changes && (!/^\d{4}-\d{2}$/.test(values.visitMonth) || values.visitMonth > maxMonth))
      errors.visit_month = t('ভ্রমণের মাস ভবিষ্যতের হতে পারবে না।', 'The visit month cannot be in the future.');
    return errors;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (!changed) return;
    const errors = validate();
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setFocusRequest((n) => n + 1);
      return;
    }
    setSaving(true);
    try {
      await onSave(changes);
    } catch (error: unknown) {
      if (error instanceof ApiError) {
        if (error.code === 'REVIEW_VERSION_CONFLICT') {
          setConflict(true);
          setFormError(t('আপনি সম্পাদনা করার সময় রিভিউটি বদলে গেছে। সর্বশেষ সংস্করণ দেখতে রিলোড করুন। আপনার লেখা নিচে রাখা আছে।', 'This review changed while you were editing. Reload to see the latest version. Your text is kept below.'));
        } else if (error.code === 'INVALID_TRANSITION') {
          setLocked(true);
          setFormError(t('রিভিউটির বর্তমান অবস্থায় আর সম্পাদনা করা যাবে না।', 'This review can no longer be edited in its current state.'));
        } else if (error.code === 'MEMBER_REVIEW_EXISTS') {
          setFieldErrors({ visit_month: t('এই গন্তব্যে এই মাসের জন্য আপনার একটি রিভিউ ইতিমধ্যে আছে।', 'You already have a review of this destination for that month.') });
        } else if (error.fieldErrors.length > 0) {
          const mapped: Record<string, string> = {};
          error.fieldErrors.forEach(({ field, code }) => {
            mapped[field] = t(...(FIELD_ERROR_LABEL[code] ?? FIELD_ERROR_LABEL.INVALID_VALUE));
          });
          setFieldErrors(mapped);
        } else {
          setFormError(describeError(error, t));
        }
      } else {
        setFormError(describeError(error, t));
      }
      setFocusRequest((n) => n + 1);
    } finally {
      setSaving(false);
    }
  };

  const errorFor = (field: string) =>
    fieldErrors[field] ? (
      <p id={`edit-${field}-error`} className="text-xs text-error-alert dark:text-red-400">
        {fieldErrors[field]}
      </p>
    ) : null;
  const describedBy = (field: string) => (fieldErrors[field] ? `edit-${field}-error` : undefined);

  return (
    <form ref={formRef} onSubmit={submit} noValidate aria-label={t('রিভিউ সম্পাদনা', 'Edit review')} className="tonal-card p-6 flex flex-col gap-5">
      {intro}
      <p role="note" className="p-3 rounded-xl bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200 text-xs">
        {t(
          'সংরক্ষণ করলে নতুন একটি সংস্করণ তৈরি হবে এবং রিভিউটি আবার মডারেটরের কাছে যাবে। অনুমোদনের আগে এটি দেখা যাবে না।',
          'Saving creates a new version and sends your review back to the moderators. It stays hidden until they approve it.',
        )}
      </p>
      {guest && (
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t('শুধু যা বদলাতে চান তা পূরণ করুন। বাকি অংশ আগের মতোই থাকবে।', 'Fill in only what you want to change. Everything else stays as it is.')}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <label htmlFor="edit-title" className={labelClass}>{t('শিরোনাম', 'Title')}</label>
        <input id="edit-title" value={values.title} maxLength={titleMax} onChange={(e) => set('title', e.target.value)} aria-invalid={Boolean(fieldErrors.title)} aria-describedby={describedBy('title')} className={inputClass} />
        {errorFor('title')}
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="edit-body" className={labelClass}>{t('আপনার নোট', 'Your note')}</label>
        <textarea id="edit-body" rows={6} value={values.body} maxLength={noteMax} onChange={(e) => set('body', e.target.value)} aria-invalid={Boolean(fieldErrors.body)} aria-describedby={`edit-body-count${fieldErrors.body ? ' edit-body-error' : ''}`} className={`${inputClass} py-3 font-body`} />
        <p id="edit-body-count" className="text-[11px] text-on-surface-variant dark:text-on-dark-muted font-en">
          {codePoints(values.body)} / {noteMax}
        </p>
        {errorFor('body')}
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className={labelClass}>{t('সার্বিক রেটিং', 'Overall rating')}</legend>
        <div className="flex items-center gap-1" role="radiogroup" aria-describedby={describedBy('overall_rating')}>
          {[1, 2, 3, 4, 5].map((star) => (
            <button key={star} type="button" role="radio" aria-checked={values.overallRating === star} aria-label={t(`${star} তারকা`, `${star} star${star === 1 ? '' : 's'}`)} onClick={() => set('overallRating', star)} className="p-1.5 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full">
              <Star size={26} aria-hidden="true" className={star <= values.overallRating ? 'fill-amber-400 text-amber-400' : 'text-surface-muted dark:text-on-dark-muted'} />
            </button>
          ))}
        </div>
        {errorFor('overall_rating')}
      </fieldset>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="edit-month" className={labelClass}>{t('ভ্রমণের মাস', 'Month of visit')}</label>
          <input id="edit-month" type="month" value={values.visitMonth} max={maxMonth} onChange={(e) => set('visitMonth', e.target.value)} aria-invalid={Boolean(fieldErrors.visit_month)} aria-describedby={describedBy('visit_month')} className={`${inputClass} font-en`} />
          {errorFor('visit_month')}
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="edit-language" className={labelClass}>{t('রিভিউয়ের ভাষা', 'Review language')}</label>
          <select id="edit-language" value={values.language} onChange={(e) => set('language', e.target.value as ReviewLanguage)} className={inputClass}>
            {REVIEW_LANGUAGES.map(([value, label]) => (<option key={value} value={value}>{t(...label)}</option>))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="edit-traveller" className={labelClass}>{t('ভ্রমণকারীর ধরন', 'Traveller type')}</label>
          <select id="edit-traveller" value={values.travellerType} onChange={(e) => set('travellerType', e.target.value as TravellerType)} className={inputClass}>
            {TRAVELLER_TYPES.map(([value, label]) => (<option key={value} value={value}>{t(...label)}</option>))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="edit-comfort" className={labelClass}>{t('খরচের ধরন', 'Comfort tier')}</label>
          <select id="edit-comfort" value={values.comfortTier} onChange={(e) => set('comfortTier', e.target.value as ComfortTier)} className={inputClass}>
            {COMFORT_TIERS.map(([value, label]) => (<option key={value} value={value}>{t(...label)}</option>))}
          </select>
        </div>
      </div>

      <CategoryRatings value={values.categoryRatings} onChange={(next) => set('categoryRatings', next)} pendingServerSupport={false} categories={parameters?.categories} />
      {guest && touched.has('categoryRatings') && (
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t('বিষয়ভিত্তিক রেটিং বদলালে এখানে দেওয়া সবগুলো আগের সেট প্রতিস্থাপন করবে।', 'If you change category ratings, the ones set here replace the earlier set.')}
        </p>
      )}

      {formError && (
        <div role="alert" tabIndex={-1} className="p-3 rounded-xl bg-error-container text-sm text-red-900 dark:bg-red-950/40 dark:text-red-200 flex flex-wrap items-center gap-3">
          <span>{formError}</span>
          {conflict && onReload && (
            <button type="button" onClick={onReload} className="inline-flex items-center gap-1.5 min-h-[44px] px-4 rounded-full border border-red-700 text-xs font-bold">
              <RefreshCw size={14} aria-hidden="true" />
              {t('রিলোড', 'Reload')}
            </button>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={saving || !changed || locked} className="inline-flex items-center gap-2 min-h-[44px] px-6 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title disabled:opacity-50">
          <Save size={16} aria-hidden="true" />
          {saving ? t('সংরক্ষণ হচ্ছে…', 'Saving…') : t('সংরক্ষণ করুন', 'Save')}
        </button>
        <button type="button" onClick={onCancel} className="min-h-[44px] px-5 rounded-full border text-sm font-bold">
          {t('বাতিল', 'Cancel')}
        </button>
        {!changed && !locked && <span className="text-xs text-on-surface-variant dark:text-on-dark-muted">{t('কিছু বদলালে সংরক্ষণ চালু হবে।', 'Save turns on when you change something.')}</span>}
      </div>
    </form>
  );
};

function snake(field: string): string {
  return field.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}
