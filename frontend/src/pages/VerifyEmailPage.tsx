import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { verifyEmail } from '../api/auth';
import { Notice, accountErrorMessage, linkClass, primaryButtonClass } from '../components/auth/AccountUi';
import { useLanguage } from '../context/LanguageContext';

type State = { phase: 'working' } | { phase: 'done' } | { phase: 'failed'; message: string } | { phase: 'missing' };

/**
 * The page behind the emailed verification link (`/verify-email?token_hash=...&type=signup`).
 * The one-time token is sent exactly once (a ref guards React StrictMode's double effect). Verifying
 * proves the address and does not sign the visitor in.
 */
export const VerifyEmailPage: React.FC = () => {
  const { t } = useLanguage();
  const [params] = useSearchParams();
  const tokenHash = params.get('token_hash');
  const started = useRef(false);
  const [state, setState] = useState<State>(tokenHash ? { phase: 'working' } : { phase: 'missing' });

  useEffect(() => {
    if (!tokenHash || started.current) return;
    started.current = true;
    verifyEmail(tokenHash)
      .then(() => setState({ phase: 'done' }))
      .catch((error) => setState({ phase: 'failed', message: accountErrorMessage(error, t) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the token is read once
  }, [tokenHash]);

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 py-10 sm:py-16 flex flex-col gap-6">
      <div className="tonal-card p-6 flex flex-col gap-4" aria-live="polite">
        {state.phase === 'working' && (
          <>
            <Loader2 size={28} className="animate-spin text-forest-primary dark:text-neon-lime" aria-hidden="true" />
            <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('যাচাই করা হচ্ছে…', 'Verifying…')}</h1>
          </>
        )}
        {state.phase === 'done' && (
          <>
            <CheckCircle2 size={28} className="text-forest-primary dark:text-neon-lime" aria-hidden="true" />
            <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('ইমেইল যাচাই হয়েছে', 'Email verified')}</h1>
            <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">{t('এখন সাইন ইন করতে পারেন।', 'You can sign in now.')}</p>
            <Link to="/login" className={`${primaryButtonClass} px-6 self-start`}>
              {t('সাইন ইন', 'Sign in')}
            </Link>
          </>
        )}
        {(state.phase === 'failed' || state.phase === 'missing') && (
          <>
            <XCircle size={28} className="text-red-600" aria-hidden="true" />
            <h1 className="text-2xl font-bold font-title text-on-surface dark:text-on-dark">{t('লিংকটি কাজ করেনি', 'This link did not work')}</h1>
            <Notice tone="error">
              {state.phase === 'failed' ? state.message : t('লিংকে যাচাই কোড নেই। ইমেইলের পুরো লিংকটি খুলুন।', 'The link has no verification code. Open the full link from the email.')}
            </Notice>
            <p className="text-sm text-on-surface-variant dark:text-on-dark-muted">
              {t('নতুন লিংক পেতে সাইন ইন পাতা থেকে "যাচাই লিংক আবার পাঠান" চাপুন।', 'To get a new link, try signing in and choose "Send the verification link again".')}
            </p>
            <Link to="/login" className={linkClass}>
              {t('সাইন ইন পাতায় যান', 'Go to sign in')}
            </Link>
          </>
        )}
      </div>
    </div>
  );
};
