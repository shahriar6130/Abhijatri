import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { MailCheck, UserPlus } from 'lucide-react';
import { ApiError } from '../api/client';
import { register, resendVerification } from '../api/auth';
import { Field, Notice, PasswordInput, accountErrorMessage, inputClass, linkClass, primaryButtonClass, problemMessage } from '../components/auth/AccountUi';
import { TURNSTILE_SITE_KEY, TurnstileWidget } from '../components/reviews/TurnstileWidget';
import { useLanguage } from '../context/LanguageContext';
import { DISPLAY_NAME_MAX, displayNameProblem, emailProblem, normalizeEmail, passwordProblem } from '../utils/authValidation';

type Errors = { email?: string; display_name?: string; password?: string };

/** Registration (Gantt R05, API.md 5.17). The answer is the same for a new and an existing address. */
export const RegisterPage: React.FC = () => {
  const { t } = useLanguage();
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [turnstile, setTurnstile] = useState<string | null>(null);
  const [challengeKey, setChallengeKey] = useState(0);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [created, setCreated] = useState(false); // the server skipped email verification (development only)
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const next: Errors = {};
    const emailIssue = emailProblem(email);
    const nameIssue = displayNameProblem(displayName);
    const passwordIssue = passwordProblem(password);
    if (emailIssue) next.email = problemMessage('email', emailIssue, t);
    if (nameIssue) next.display_name = problemMessage('display_name', nameIssue, t);
    if (passwordIssue) next.password = problemMessage('password', passwordIssue, t);
    setErrors(next);
    setFormError(null);
    if (Object.keys(next).length > 0) return;
    if (TURNSTILE_SITE_KEY && !turnstile) {
      setFormError(t('নিরাপত্তা যাচাই শেষ হওয়া পর্যন্ত অপেক্ষা করুন।', 'Wait for the security check to finish.'));
      return;
    }
    setBusy(true);
    try {
      const answer = await register({ email: normalizeEmail(email), password, display_name: displayName.normalize('NFC').trim(), turnstile_token: turnstile });
      setCreated(answer.status === 'registered');
      setSentTo(normalizeEmail(email));
      setPassword('');
    } catch (error) {
      if (error instanceof ApiError && error.fieldErrors.length > 0) {
        const server: Errors = {};
        for (const item of error.fieldErrors) {
          if (item.field === 'email' || item.field === 'password' || item.field === 'display_name') {
            server[item.field] = problemMessage(item.field, item.code, t);
          }
        }
        setErrors(server);
      }
      setFormError(accountErrorMessage(error, t));
    } finally {
      setTurnstile(null); // a Turnstile token is single use
      setChallengeKey((key) => key + 1);
      setBusy(false);
    }
  };

  const resend = async () => {
    if (!sentTo) return;
    setResent(false);
    try {
      await resendVerification(sentTo);
      setResent(true);
    } catch (error) {
      setFormError(accountErrorMessage(error, t));
    }
  };

  if (sentTo && created) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
        <div className="tonal-card p-6 flex flex-col gap-3">
          <MailCheck size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('অ্যাকাউন্ট তৈরি হয়েছে', 'Account created')}</h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t(`${sentTo} দিয়ে এখনই সাইন ইন করুন।`, `Sign in now with ${sentTo}.`)}
          </p>
          <Link to="/login" className={linkClass}>
            {t('সাইন ইন', 'Sign in')}
          </Link>
        </div>
      </div>
    );
  }

  if (sentTo) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
        <div className="tonal-card p-6 flex flex-col gap-3">
          <MailCheck size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('ইমেইল দেখুন', 'Check your email')}</h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t(
              `${sentTo} ঠিকানায় একটি যাচাই লিংক পাঠানো হয়েছে (যদি এটি নতুন হয়)। লিংকটি ২৪ ঘণ্টা কার্যকর। যাচাইয়ের পর সাইন ইন করুন।`,
              `We sent a verification link to ${sentTo}. It works for 24 hours. After verifying, sign in.`,
            )}
          </p>
          {resent && <Notice tone="success">{t('আবার পাঠানো হয়েছে।', 'Sent again.')}</Notice>}
          {formError && <Notice tone="error">{formError}</Notice>}
          <div className="flex flex-wrap gap-4 text-sm">
            <button type="button" onClick={resend} className={linkClass}>
              {t('লিংক আবার পাঠান', 'Send the link again')}
            </button>
            <Link to="/login" className={linkClass}>
              {t('সাইন ইন', 'Sign in')}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">{t('অ্যাকাউন্ট খুলুন', 'Create an account')}</h1>
        <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
          {t('রিভিউয়ের জন্য অ্যাকাউন্ট বাধ্যতামূলক নয়; অতিথি হিসেবেও রিভিউ দেওয়া যায়।', 'An account is optional: guests can still write reviews.')}
        </p>
      </div>

      {formError && <Notice tone="error">{formError}</Notice>}

      <form className="tonal-card p-6 flex flex-col gap-4" onSubmit={submit} noValidate>
        <Field id="register-email" label={t('ইমেইল', 'Email')} error={errors.email}>
          {(a) => (
            <input {...a} type="email" autoComplete="email" inputMode="email" value={email} disabled={busy} onChange={(e) => setEmail(e.target.value)} className={inputClass} />
          )}
        </Field>
        <Field
          id="register-name"
          label={t('প্রদর্শন নাম', 'Display name')}
          error={errors.display_name}
          hint={t('রিভিউয়ে এই নাম দেখা যাবে।', 'This name appears on your reviews.')}
        >
          {(a) => (
            <input {...a} type="text" autoComplete="nickname" maxLength={DISPLAY_NAME_MAX} value={displayName} disabled={busy} onChange={(e) => setDisplayName(e.target.value)} className={inputClass} />
          )}
        </Field>
        <Field
          id="register-password"
          label={t('পাসওয়ার্ড', 'Password')}
          error={errors.password}
          hint={t('কমপক্ষে ১০ অক্ষর, একটি অক্ষর ও একটি সংখ্যা সহ। পেস্ট করা যাবে।', 'At least 10 characters with a letter and a number. Pasting is fine.')}
        >
          {(a) => (
            <PasswordInput id={a.id} value={password} onChange={setPassword} autoComplete="new-password" invalid={a['aria-invalid']} describedBy={a['aria-describedby']} showStrength disabled={busy} />
          )}
        </Field>
        <TurnstileWidget key={challengeKey} action="auth-register" onToken={setTurnstile} />
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          <UserPlus size={16} aria-hidden="true" />
          {busy ? t('অপেক্ষা করুন…', 'Please wait…') : t('অ্যাকাউন্ট খুলুন', 'Create account')}
        </button>
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t('আগেই অ্যাকাউন্ট আছে?', 'Already have an account?')}{' '}
          <Link to="/login" className={linkClass}>
            {t('সাইন ইন', 'Sign in')}
          </Link>
        </p>
      </form>
    </div>
  );
};
