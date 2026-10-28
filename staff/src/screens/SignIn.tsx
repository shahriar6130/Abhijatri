import { useState, type FormEvent } from 'react';
import { getSession, login, logout, mfaEnroll, mfaVerify } from '../api';
import { errorText, qrImageSource } from '../logic';
import type { Enrollment, Lang, Session, SignedIn } from '../types';
import { Notice, makeT } from '../ui';

interface Props {
  lang: Lang;
  session: Session;
  onSession: (session: Session) => void;
}

/**
 * Staff sign-in in three steps: password, then the authenticator code (enrolling the app the first
 * time), then the dashboard. A signed-in account without a staff role is told so and can leave.
 */
export function SignIn({ lang, session, onSession }: Props) {
  const t = makeT(lang);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      setError(errorText(failure, lang));
    } finally {
      setBusy(false);
    }
  };

  const submitPassword = (event: FormEvent) => {
    event.preventDefault();
    void attempt(async () => {
      onSession(await login(email.trim().toLowerCase(), password));
      setPassword('');
    });
  };

  const startEnrollment = () => void attempt(async () => setEnrollment(await mfaEnroll()));

  const submitCode = (factorId: string) => (event: FormEvent) => {
    event.preventDefault();
    void attempt(async () => {
      await mfaVerify(factorId, code);
      setCode('');
      onSession(await getSession());
    });
  };

  const leave = () => void attempt(async () => {
    await logout();
    setEnrollment(null);
    onSession({ authenticated: false });
  });

  const signedIn: SignedIn | null = session.authenticated ? session : null;

  return (
    <main className="login">
      <div className="card login-card">
        <h1>{t('অভিযাত্রী স্টাফ ড্যাশবোর্ড', 'Abhijatri staff dashboard')}</h1>
        {error && <Notice tone="error">{error}</Notice>}

        {!signedIn && (
          <form className="stack" onSubmit={submitPassword}>
            <p className="muted small">{t('স্টাফ অ্যাকাউন্ট দিয়ে সাইন ইন করুন।', 'Sign in with your staff account.')}</p>
            <label htmlFor="staff-email">{t('ইমেইল', 'Email')}</label>
            <input id="staff-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            <label htmlFor="staff-password">{t('পাসওয়ার্ড', 'Password')}</label>
            <input id="staff-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <button type="submit" className="primary" disabled={busy || !email || !password}>
              {busy ? '…' : t('সাইন ইন', 'Sign in')}
            </button>
          </form>
        )}

        {signedIn && signedIn.role === null && (
          <>
            <Notice tone="info">
              {t(`${signedIn.user.display_name}, আপনার অ্যাকাউন্টে স্টাফ ভূমিকা নেই।`, `${signedIn.user.display_name}, this account has no staff role.`)}
            </Notice>
            <button type="button" className="ghost" onClick={leave}>
              {t('সাইন আউট', 'Sign out')}
            </button>
          </>
        )}

        {signedIn && signedIn.role !== null && signedIn.aal !== 'aal2' && (
          <div className="stack">
            <p className="muted small">
              {t(`${signedIn.user.display_name} (${signedIn.role}) — দ্বি-স্তরের যাচাই প্রয়োজন।`, `${signedIn.user.display_name} (${signedIn.role}) — two-step verification is required.`)}
            </p>

            {signedIn.mfa_factors.length === 0 && !enrollment && (
              <button type="button" className="primary" onClick={startEnrollment} disabled={busy}>
                {t('অথেনটিকেটর অ্যাপ সেট করুন', 'Set up an authenticator app')}
              </button>
            )}

            {enrollment && (
              <div className="stack">
                <p className="small">
                  {t(
                    'Google Authenticator, Authy বা অন্য TOTP অ্যাপে এই QR স্ক্যান করুন, তারপর ৬ সংখ্যার কোড দিন।',
                    'Scan this QR code with Google Authenticator, Authy or any TOTP app, then enter the 6-digit code.',
                  )}
                </p>
                {qrImageSource(enrollment.qr_code) && (
                  <img className="qr" alt={t('QR কোড', 'QR code')} src={qrImageSource(enrollment.qr_code) as string} width={180} height={180} />
                )}
                <p className="small muted">
                  {t('QR না চললে এই গোপন কী নিজে লিখুন:', 'If scanning fails, type this secret key:')} <code>{enrollment.secret}</code>
                </p>
                <CodeForm lang={lang} code={code} setCode={setCode} busy={busy} onSubmit={submitCode(enrollment.factor_id)} />
              </div>
            )}

            {signedIn.mfa_factors.length > 0 && (
              <CodeForm lang={lang} code={code} setCode={setCode} busy={busy} onSubmit={submitCode(signedIn.mfa_factors[0].id)} />
            )}

            <button type="button" className="ghost" onClick={leave}>
              {t('সাইন আউট', 'Sign out')}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}

function CodeForm({ lang, code, setCode, busy, onSubmit }: { lang: Lang; code: string; setCode: (v: string) => void; busy: boolean; onSubmit: (e: FormEvent) => void }) {
  const t = makeT(lang);
  return (
    <form className="stack" onSubmit={onSubmit}>
      <label htmlFor="totp-code">{t('অথেনটিকেটর কোড', 'Authenticator code')}</label>
      <input id="totp-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
      <button type="submit" className="primary" disabled={busy || code.length !== 6}>
        {busy ? '…' : t('যাচাই করুন', 'Verify')}
      </button>
    </form>
  );
}
