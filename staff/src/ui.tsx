import { useState, type FormEvent, type ReactNode } from 'react';
import { reauth } from './api';
import { errorText } from './logic';
import type { Lang } from './types';

export type T = (bn: string, en: string) => string;
export const makeT = (lang: Lang): T => (bn, en) => (lang === 'bn' ? bn : en);

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'error' | 'success'; children: ReactNode }) {
  return (
    <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

/**
 * Asks for the password again (and the authenticator code when one is enrolled) before a
 * high-impact action such as changing a staff role (Moderation spec 4.1). On success the server
 * issues a session with a fresh confirmation time and the caller retries its action.
 */
export function ReauthDialog({ lang, needsCode, onDone, onCancel }: { lang: Lang; needsCode: boolean; onDone: () => void; onCancel: () => void }) {
  const t = makeT(lang);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await reauth(password, needsCode ? code : undefined);
      onDone();
    } catch (failure) {
      setError(errorText(failure, lang));
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="reauth-title">
      <form className="card modal-card" onSubmit={submit}>
        <h2 id="reauth-title">{t('আবার যাচাই করুন', 'Confirm it is you')}</h2>
        <p className="muted small">{t('এই কাজটি স্পর্শকাতর। পাসওয়ার্ড দিন।', 'This action is sensitive. Enter your password again.')}</p>
        {error && <Notice tone="error">{error}</Notice>}
        <label htmlFor="reauth-password">{t('পাসওয়ার্ড', 'Password')}</label>
        <input id="reauth-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        {needsCode && (
          <>
            <label htmlFor="reauth-code">{t('অথেনটিকেটর কোড (৬ সংখ্যা)', 'Authenticator code (6 digits)')}</label>
            <input id="reauth-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
          </>
        )}
        <div className="row">
          <button type="submit" className="primary" disabled={busy || !password || (needsCode && code.length !== 6)}>
            {busy ? '…' : t('নিশ্চিত করুন', 'Confirm')}
          </button>
          <button type="button" className="ghost" onClick={onCancel}>
            {t('বাতিল', 'Cancel')}
          </button>
        </div>
      </form>
    </div>
  );
}
