import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { MailCheck, Send } from 'lucide-react';
import { requestPasswordReset } from '../api/auth';
import { Field, Notice, accountErrorMessage, inputClass, linkClass, primaryButtonClass, problemMessage } from '../components/auth/AccountUi';
import { TURNSTILE_SITE_KEY, TurnstileWidget } from '../components/reviews/TurnstileWidget';
import { useLanguage } from '../context/LanguageContext';
import { emailProblem, normalizeEmail } from '../utils/authValidation';

/** Ask for a reset link. The answer is the same for every address, so it never says who has an account. */
export const ForgotPasswordPage: React.FC = () => {
  const { t } = useLanguage();
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  const [turnstile, setTurnstile] = useState<string | null>(null);
  const [challengeKey, setChallengeKey] = useState(0);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const issue = emailProblem(email);
    setError(issue ? problemMessage('email', issue, t) : undefined);
    setFormError(null);
    if (issue) return;
    if (TURNSTILE_SITE_KEY && !turnstile) {
      setFormError(t('নিরাপত্তা যাচাই শেষ হওয়া পর্যন্ত অপেক্ষা করুন।', 'Wait for the security check to finish.'));
      return;
    }
    setBusy(true);
    try {
      await requestPasswordReset(normalizeEmail(email), turnstile);
      setSent(true);
    } catch (failure) {
      setFormError(accountErrorMessage(failure, t));
    } finally {
      setTurnstile(null);
      setChallengeKey((key) => key + 1);
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
        <div className="tonal-card p-6 flex flex-col gap-3">
          <MailCheck size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
          <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('ইমেইল দেখুন', 'Check your email')}</h1>
          <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
            {t(
              'এই ঠিকানায় অ্যাকাউন্ট থাকলে একটি রিসেট লিংক পাঠানো হয়েছে। লিংকটি ১ ঘণ্টা কার্যকর।',
              'If an account exists for this address, we sent a reset link. It works for 1 hour.',
            )}
          </p>
          <Link to="/login" className={linkClass}>
            {t('সাইন ইন পাতায় ফিরুন', 'Back to sign in')}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">{t('পাসওয়ার্ড রিসেট', 'Reset your password')}</h1>
        <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{t('আপনার ইমেইল দিন, আমরা একটি রিসেট লিংক পাঠাব।', 'Enter your email and we will send a reset link.')}</p>
      </div>
      {formError && <Notice tone="error">{formError}</Notice>}
      <form className="tonal-card p-6 flex flex-col gap-4" onSubmit={submit} noValidate>
        <Field id="forgot-email" label={t('ইমেইল', 'Email')} error={error}>
          {(a) => <input {...a} type="email" autoComplete="email" inputMode="email" value={email} disabled={busy} onChange={(e) => setEmail(e.target.value)} className={inputClass} />}
        </Field>
        <TurnstileWidget key={challengeKey} action="auth-reset" onToken={setTurnstile} />
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          <Send size={16} aria-hidden="true" />
          {busy ? t('অপেক্ষা করুন…', 'Please wait…') : t('রিসেট লিংক পাঠান', 'Send reset link')}
        </button>
        <Link to="/login" className={`${linkClass} text-xs`}>
          {t('সাইন ইন পাতায় ফিরুন', 'Back to sign in')}
        </Link>
      </form>
    </div>
  );
};
