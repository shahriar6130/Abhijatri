import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, LogIn } from 'lucide-react';
import { ApiError } from '../api/client';
import { resendVerification } from '../api/auth';
import { Field, Notice, PasswordInput, accountErrorMessage, inputClass, linkClass, primaryButtonClass, problemMessage } from '../components/auth/AccountUi';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import { emailProblem, normalizeEmail } from '../utils/authValidation';

/**
 * Member sign-in (Gantt R05, API.md 5.17). The browser sends the email and password to this API,
 * which keeps the tokens in HttpOnly cookies; this page never sees one. Guests are never forced
 * here: every guide stays open without an account.
 */
export const SignInPage: React.FC = () => {
  const { t } = useLanguage();
  const { session, signIn } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const target = (location.state as { from?: string } | null)?.from ?? '/overview';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const next: { email?: string; password?: string } = {};
    const emailIssue = emailProblem(email);
    if (emailIssue) next.email = problemMessage('email', emailIssue, t);
    if (!password) next.password = problemMessage('password', 'REQUIRED', t);
    setErrors(next);
    setFormError(null);
    setUnverified(false);
    if (Object.keys(next).length > 0) return;
    setBusy(true);
    try {
      await signIn(normalizeEmail(email), password);
      navigate(target, { replace: true });
    } catch (error) {
      setUnverified(error instanceof ApiError && error.code === 'EMAIL_NOT_VERIFIED');
      setFormError(accountErrorMessage(error, t));
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setResent(false);
    try {
      await resendVerification(normalizeEmail(email));
      setResent(true);
    } catch (error) {
      setFormError(accountErrorMessage(error, t));
    }
  };

  if (session.kind === 'member') {
    return (
      <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
        <Notice tone="success">
          {t(`আপনি ${session.displayName} হিসেবে সাইন ইন করা আছেন।`, `You are signed in as ${session.displayName}.`)}
        </Notice>
        <Link to="/overview" className={`${primaryButtonClass} px-6 self-start`}>
          {t('চালিয়ে যান', 'Continue')}
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark">{t('সাইন ইন', 'Sign in')}</h1>
        <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
          {t('আপনার অভিযাত্রী সদস্য অ্যাকাউন্টে প্রবেশ করুন।', 'Sign in to your Abhijatri member account.')}
        </p>
      </div>

      {formError && (
        <Notice tone="error">
          <p>{formError}</p>
          {unverified && (
            <button type="button" onClick={resend} className={`${linkClass} mt-2`}>
              {t('যাচাই লিংক আবার পাঠান', 'Send the verification link again')}
            </button>
          )}
        </Notice>
      )}
      {resent && <Notice tone="success">{t('ইমেইল পাঠানো হয়েছে, যদি অ্যাকাউন্টটি থাকে। ইনবক্স দেখুন।', 'If the account exists, we sent the email. Check your inbox.')}</Notice>}

      <form className="tonal-card p-6 flex flex-col gap-4" onSubmit={submit} noValidate>
        <Field id="signin-email" label={t('ইমেইল', 'Email')} error={errors.email}>
          {(a) => (
            <input
              {...a}
              type="email"
              autoComplete="email"
              inputMode="email"
              value={email}
              disabled={busy}
              onChange={(event) => setEmail(event.target.value)}
              className={inputClass}
            />
          )}
        </Field>
        <Field id="signin-password" label={t('পাসওয়ার্ড', 'Password')} error={errors.password}>
          {(a) => (
            <PasswordInput
              id={a.id}
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              invalid={a['aria-invalid']}
              describedBy={a['aria-describedby']}
              disabled={busy}
            />
          )}
        </Field>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          <LogIn size={16} aria-hidden="true" />
          {busy ? t('অপেক্ষা করুন…', 'Please wait…') : t('সাইন ইন', 'Sign in')}
        </button>
        <div className="flex flex-wrap justify-between gap-2 text-xs">
          <Link to="/forgot-password" className={linkClass}>
            {t('পাসওয়ার্ড ভুলে গেছেন?', 'Forgot your password?')}
          </Link>
          <Link to="/register" className={linkClass}>
            {t('নতুন অ্যাকাউন্ট খুলুন', 'Create an account')}
          </Link>
        </div>
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {t(
            'সাইন আপের পর "যাচাইকৃত সদস্য" হতে আলাদা একটি অনুমোদিত যাচাই লাগবে; ইমেইল যাচাই একা যথেষ্ট নয়।',
            'After signing up, becoming a Verified Member needs a separate approved verification; email verification alone is not enough.',
          )}
        </p>
      </form>

      <Link
        to="/overview"
        className="self-center inline-flex items-center gap-2 min-h-[44px] px-5 rounded-full bg-surface-sage dark:bg-dark-surface-1 text-forest-primary dark:text-neon-lime text-sm font-bold font-title"
      >
        {t('অতিথি হিসেবে চালিয়ে যান', 'Continue as guest')}
        <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </div>
  );
};
