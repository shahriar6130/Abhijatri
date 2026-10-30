import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { ApiError, NETWORK_ERROR } from '../../api/client';
import { useLanguage } from '../../context/LanguageContext';
import { passwordStrength, type FieldProblem } from '../../utils/authValidation';

/** Small building blocks shared by the account pages (sign in, register, verify, reset). */

type Translate = (bn: string, en: string) => string;

export const inputClass =
  'w-full px-3.5 min-h-[44px] rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/50 dark:border-dark-surface-2 text-sm text-on-surface dark:text-on-dark disabled:opacity-60 disabled:cursor-not-allowed aria-[invalid=true]:border-red-500';

export const primaryButtonClass =
  'inline-flex items-center justify-center gap-2 min-h-[48px] rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-sm font-bold font-title disabled:opacity-50 disabled:cursor-not-allowed';

export const linkClass = 'text-forest-primary dark:text-neon-lime font-bold underline underline-offset-2';

/** A field problem as a sentence in the reader's language. */
export function problemMessage(field: 'email' | 'password' | 'display_name', problem: FieldProblem | string, t: Translate): string {
  switch (field) {
    case 'email':
      return problem === 'REQUIRED' ? t('ইমেইল দিন।', 'Enter your email.') : t('সঠিক ইমেইল ঠিকানা দিন।', 'Enter a valid email address.');
    case 'password':
      if (problem === 'REQUIRED') return t('পাসওয়ার্ড দিন।', 'Enter a password.');
      if (problem === 'TOO_SHORT') return t('কমপক্ষে ১০ অক্ষর দিন।', 'Use at least 10 characters.');
      if (problem === 'TOO_LONG') return t('পাসওয়ার্ড ১২৮ অক্ষরের বেশি হতে পারবে না।', 'A password can be at most 128 characters.');
      if (problem === 'SAME_PASSWORD') return t('নতুন পাসওয়ার্ড বর্তমানটির থেকে আলাদা হতে হবে।', 'The new password must be different from your current one.');
      return t('অন্তত একটি অক্ষর ও একটি সংখ্যা থাকতে হবে।', 'Include at least one letter and one number.');
    default:
      if (problem === 'INVALID_VALUE') return t('নাম ইমেইল ঠিকানা হতে পারবে না। আপনার নাম লিখুন।', 'A name cannot be an email address. Enter your name.');
      return problem === 'REQUIRED' ? t('আপনার নাম দিন।', 'Enter your name.') : t('নাম ৮০ অক্ষরের বেশি হতে পারবে না।', 'A name can be at most 80 characters.');
  }
}

/** The page-level message for a failed account call. It never says whether an email has an account. */
export function accountErrorMessage(error: unknown, t: Translate): string {
  if (!(error instanceof ApiError)) return t('একটি ত্রুটি ঘটেছে। আবার চেষ্টা করুন।', 'Something went wrong. Try again.');
  switch (error.code) {
    case NETWORK_ERROR:
      return t('সার্ভারের সাথে সংযোগ করা যায়নি। ইন্টারনেট দেখে আবার চেষ্টা করুন।', 'Could not reach the server. Check your connection and try again.');
    case 'INVALID_CREDENTIALS':
      return t('ইমেইল বা পাসওয়ার্ড সঠিক নয়।', 'The email or password is not correct.');
    case 'EMAIL_NOT_VERIFIED':
      return t('আগে আপনার ইমেইল যাচাই করুন। ইনবক্সের লিংকটি খুলুন।', 'Verify your email first. Open the link in your inbox.');
    case 'ACCOUNT_DISABLED':
      return t('এই অ্যাকাউন্টটি বন্ধ করা হয়েছে।', 'This account has been disabled.');
    case 'RATE_LIMITED':
      return t('অনেকবার চেষ্টা করা হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।', 'Too many attempts. Try again in a little while.');
    case 'CHALLENGE_FAILED':
      return t('নিরাপত্তা যাচাই ব্যর্থ হয়েছে। আবার চেষ্টা করুন।', 'The security check failed. Try again.');
    case 'RESERVED_DISPLAY_NAME':
      return t('এই নামটি ব্যবহার করা যাবে না। অন্য নাম দিন।', 'This name cannot be used. Choose another.');
    case 'TOKEN_INVALID_OR_EXPIRED':
      return t('লিংকটি সঠিক নয় বা মেয়াদ শেষ হয়েছে।', 'This link is not valid or has expired.');
    case 'AUTH_NOT_CONFIGURED':
      return t('সাইন-ইন সেবা এখনও চালু হয়নি।', 'Sign-in is not available yet.');
    case 'SERVICE_UNAVAILABLE':
      return t('সেবাটি এখন পাওয়া যাচ্ছে না। একটু পরে চেষ্টা করুন।', 'The service is unavailable right now. Try again shortly.');
    default:
      return t('অনুরোধটি সম্পন্ন করা যায়নি।', 'The request could not be completed.');
  }
}

interface FieldProps {
  id: string;
  label: string;
  error?: string | null;
  hint?: string;
  children: (props: { id: string; 'aria-invalid': boolean; 'aria-describedby': string | undefined }) => React.ReactNode;
}

export const Field: React.FC<FieldProps> = ({ id, label, error, hint, children }) => {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(' ') || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
        {label}
      </label>
      {children({ id, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy })}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-on-surface-variant dark:text-on-dark-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs font-semibold text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
};

interface PasswordInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: 'current-password' | 'new-password';
  invalid: boolean;
  describedBy?: string;
  showStrength?: boolean;
  disabled?: boolean;
}

/** Paste is allowed (accessible authentication); the eye button shows the password. */
export const PasswordInput: React.FC<PasswordInputProps> = ({ id, value, onChange, autoComplete, invalid, describedBy, showStrength, disabled }) => {
  const { t } = useLanguage();
  const [shown, setShown] = useState(false);
  const strength = passwordStrength(value);
  const labels = [t('খুব দুর্বল', 'Very weak'), t('দুর্বল', 'Weak'), t('ঠিক আছে', 'Good'), t('শক্তিশালী', 'Strong')];
  return (
    <div className="flex flex-col gap-1.5">
      <div className="relative">
        <input
          id={id}
          type={shown ? 'text' : 'password'}
          autoComplete={autoComplete}
          spellCheck={false}
          value={value}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
          className={`${inputClass} pr-12`}
        />
        <button
          type="button"
          onClick={() => setShown((current) => !current)}
          aria-label={shown ? t('পাসওয়ার্ড লুকান', 'Hide password') : t('পাসওয়ার্ড দেখান', 'Show password')}
          aria-pressed={shown}
          className="absolute inset-y-0 right-0 w-11 inline-flex items-center justify-center text-on-surface-variant dark:text-on-dark-muted"
        >
          {shown ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
        </button>
      </div>
      {showStrength && value && (
        <p className="text-xs text-on-surface-variant dark:text-on-dark-muted" aria-live="polite">
          {t('শক্তি', 'Strength')}: {labels[strength]}
        </p>
      )}
    </div>
  );
};

export const Notice: React.FC<{ tone: 'info' | 'error' | 'success'; children: React.ReactNode }> = ({ tone, children }) => {
  const tones = {
    info: 'bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:border-amber-900/50 dark:text-amber-200',
    error: 'bg-red-50 border-red-200 text-red-900 dark:bg-red-950/30 dark:border-red-900/50 dark:text-red-200',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-900 dark:bg-emerald-950/30 dark:border-emerald-900/50 dark:text-emerald-200',
  };
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`p-4 rounded-xl border text-sm ${tones[tone]}`}>
      {children}
    </div>
  );
};
