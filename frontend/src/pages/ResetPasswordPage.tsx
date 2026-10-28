import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2, KeyRound } from 'lucide-react';
import { ApiError } from '../api/client';
import { confirmPasswordReset } from '../api/auth';
import { Field, Notice, PasswordInput, accountErrorMessage, linkClass, primaryButtonClass, problemMessage } from '../components/auth/AccountUi';
import { useLanguage } from '../context/LanguageContext';
import { passwordProblem } from '../utils/authValidation';

/** The page behind the emailed reset link (`/reset-password?token_hash=...&type=recovery`). */
export const ResetPasswordPage: React.FC = () => {
  const { t } = useLanguage();
  const [params] = useSearchParams();
  const tokenHash = params.get('token_hash');
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [errors, setErrors] = useState<{ password?: string; again?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [linkDead, setLinkDead] = useState(false);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!tokenHash) return;
    const next: { password?: string; again?: string } = {};
    const issue = passwordProblem(password);
    if (issue) next.password = problemMessage('password', issue, t);
    if (!issue && password !== again) next.again = t('দুটি পাসওয়ার্ড মেলেনি।', 'The two passwords do not match.');
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    try {
      await confirmPasswordReset(tokenHash, password);
      setDone(true);
    } catch (error) {
      const same = error instanceof ApiError && error.fieldErrors.some((f) => f.field === 'password' && f.code === 'SAME_PASSWORD');
      if (same) {
        // Supabase spends the link before it compares passwords, so a new link is needed for the next try.
        setErrors({ password: problemMessage('password', 'SAME_PASSWORD', t) });
        setLinkDead(true);
        setFormError(
          t(
            'নতুন পাসওয়ার্ড বর্তমানটির মতোই ছিল। এই লিংকটি ব্যবহার হয়ে গেছে: নতুন লিংক চেয়ে অন্য একটি পাসওয়ার্ড দিন।',
            'The new password was the same as your current one. This link has now been used: ask for a new link and choose a different password.',
          ),
        );
        return;
      }
      if (error instanceof ApiError && error.code === 'TOKEN_INVALID_OR_EXPIRED') setLinkDead(true);
      setFormError(accountErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16">
        <div className="tonal-card p-6 flex flex-col gap-3">
          <CheckCircle2 size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('পাসওয়ার্ড বদলানো হয়েছে', 'Password changed')}</h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t('নিরাপত্তার জন্য সব ডিভাইস থেকে সাইন আউট করা হয়েছে। নতুন পাসওয়ার্ড দিয়ে সাইন ইন করুন।', 'For safety every device was signed out. Sign in with your new password.')}
          </p>
          <Link to="/login" className={`${primaryButtonClass} px-6 self-start`}>
            {t('সাইন ইন', 'Sign in')}
          </Link>
        </div>
      </div>
    );
  }

  if (!tokenHash || linkDead) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-4">
        <Notice tone="error">{formError ?? t('রিসেট লিংকে কোড নেই। ইমেইলের পুরো লিংকটি খুলুন।', 'The reset link has no code. Open the full link from the email.')}</Notice>
        <Link to="/forgot-password" className={linkClass}>
          {t('নতুন রিসেট লিংক চান', 'Ask for a new reset link')}
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">{t('নতুন পাসওয়ার্ড দিন', 'Choose a new password')}</h1>
      </div>
      {formError && <Notice tone="error">{formError}</Notice>}
      <form className="tonal-card p-6 flex flex-col gap-4" onSubmit={submit} noValidate>
        <Field id="reset-password" label={t('নতুন পাসওয়ার্ড', 'New password')} error={errors.password} hint={t('কমপক্ষে ১০ অক্ষর, একটি অক্ষর ও একটি সংখ্যা সহ।', 'At least 10 characters with a letter and a number.')}>
          {(a) => <PasswordInput id={a.id} value={password} onChange={setPassword} autoComplete="new-password" invalid={a['aria-invalid']} describedBy={a['aria-describedby']} showStrength disabled={busy} />}
        </Field>
        <Field id="reset-again" label={t('আবার লিখুন', 'Repeat the password')} error={errors.again}>
          {(a) => <PasswordInput id={a.id} value={again} onChange={setAgain} autoComplete="new-password" invalid={a['aria-invalid']} describedBy={a['aria-describedby']} disabled={busy} />}
        </Field>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          <KeyRound size={16} aria-hidden="true" />
          {busy ? t('অপেক্ষা করুন…', 'Please wait…') : t('পাসওয়ার্ড বদলান', 'Change password')}
        </button>
      </form>
    </div>
  );
};
