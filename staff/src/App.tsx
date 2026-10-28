import { useCallback, useEffect, useState } from 'react';
import { StaffError, getSession, logout } from './api';
import { Audit } from './screens/Audit';
import { Enforcement } from './screens/Enforcement';
import { Inbox } from './screens/Inbox';
import { Media } from './screens/Media';
import { Notifications } from './screens/Notifications';
import { Monitor } from './screens/Monitor';
import { Queue } from './screens/Queue';
import { SignIn } from './screens/SignIn';
import { StaffRoles } from './screens/Staff';
import type { Lang, Session } from './types';
import { Notice, makeT } from './ui';

type View = 'queue' | 'inbox' | 'media' | 'enforcement' | 'audit' | 'staff' | 'monitor' | 'notifications';

/**
 * The staff shell. It shows only what the signed-in role may use, but that is a convenience: every
 * request is authorised again on the server (Moderation spec 2.1).
 */
export function App() {
  const [lang, setLang] = useState<Lang>('en');
  const [session, setSession] = useState<Session | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [view, setView] = useState<View>('queue');
  const t = makeT(lang);

  useEffect(() => {
    getSession()
      .then(setSession)
      .catch((failure) => {
        setSession({ authenticated: false });
        setStartupError(failure instanceof StaffError && failure.code === 'NETWORK_ERROR' ? 'NETWORK' : null);
      });
  }, []);

  const signOut = useCallback(async () => {
    await logout().catch(() => undefined);
    setSession({ authenticated: false });
    setView('queue');
  }, []);

  if (session === null) return <p className="muted shell">{t('লোড হচ্ছে…', 'Loading…')}</p>;

  const ready = session.authenticated && session.role !== null && session.aal === 'aal2';
  if (!session.authenticated || !ready || session.role === null) {
    return (
      <>
        {startupError && (
          <div className="shell">
            <Notice tone="error">{t('API-তে পৌঁছানো যায়নি।', 'Could not reach the API.')}</Notice>
          </div>
        )}
        <SignIn lang={lang} session={session} onSession={setSession} />
        <div className="lang-corner">
          <button type="button" className="ghost" onClick={() => setLang(lang === 'en' ? 'bn' : 'en')}>
            {lang === 'en' ? 'বাংলা' : 'English'}
          </button>
        </div>
      </>
    );
  }

  const role = session.role;
  const tabs: { id: View; label: string; show: boolean }[] = [
    { id: 'queue', label: t('কাজের সারি', 'Queue'), show: true },
    { id: 'inbox', label: t('ইনবক্স', 'Inbox'), show: true },
    { id: 'media', label: t('ছবি ও ভিডিও', 'Media'), show: true },
    { id: 'enforcement', label: t('এনফোর্সমেন্ট', 'Enforcement'), show: true },
    { id: 'audit', label: t('অডিট', 'Audit'), show: true },
    { id: 'monitor', label: t('পর্যবেক্ষণ', 'Monitoring'), show: true },
    { id: 'staff', label: t('স্টাফ', 'Staff'), show: role === 'superadmin' },
    { id: 'notifications', label: t('বিজ্ঞপ্তি ব্যবস্থা', 'Notifications'), show: role === 'superadmin' },
  ];

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>{t('মডারেশন ড্যাশবোর্ড', 'Moderation dashboard')}</h1>
          <p className="muted small">
            {session.user.display_name} · <strong>{role}</strong> · {t('সব সিদ্ধান্ত অডিট লগে যায়।', 'every decision is audited.')}
          </p>
        </div>
        <div className="row">
          <nav className="segmented" aria-label={t('বিভাগ', 'Sections')}>
            {tabs
              .filter((tab) => tab.show)
              .map((tab) => (
                <button key={tab.id} type="button" aria-pressed={view === tab.id} onClick={() => setView(tab.id)}>
                  {tab.label}
                </button>
              ))}
          </nav>
          <button type="button" className="ghost" onClick={() => setLang(lang === 'en' ? 'bn' : 'en')}>
            {lang === 'en' ? 'বাংলা' : 'English'}
          </button>
          <button type="button" className="ghost" onClick={() => void signOut()}>
            {t('সাইন আউট', 'Sign out')}
          </button>
        </div>
      </header>
      {view === 'queue' && <Queue lang={lang} role={role} userId={session.user.id} />}
      {view === 'inbox' && <Inbox lang={lang} />}
      {view === 'media' && <Media lang={lang} />}
      {view === 'notifications' && role === 'superadmin' && <Notifications lang={lang} />}
      {view === 'enforcement' && <Enforcement lang={lang} role={role} />}
      {view === 'audit' && <Audit lang={lang} />}
      {view === 'monitor' && <Monitor lang={lang} />}
      {view === 'staff' && role === 'superadmin' && <StaffRoles lang={lang} hasAuthenticator={session.mfa_factors.length > 0} />}
    </div>
  );
}
