import { useCallback, useEffect, useState } from 'react';
import { BlockList } from './Blocks';
import {
  API_BASE,
  OpsError,
  describeError,
  getCatalogue,
  getOverview,
  getPanel,
  loadToken,
  orderByCatalogue,
  runRollup,
  saveToken,
} from './api';
import { formatTime } from './format';
import type { Days, Lang, PanelData } from './types';

const DAY_CHOICES: Days[] = [7, 30, 90];

export function App() {
  const [token, setToken] = useState<string | null>(loadToken);
  const [lang, setLang] = useState<Lang>('en');

  const signOut = useCallback(() => {
    saveToken(null);
    setToken(null);
  }, []);

  return token ? (
    <Dashboard token={token} lang={lang} setLang={setLang} onSignOut={signOut} />
  ) : (
    <TokenPrompt
      lang={lang}
      setLang={setLang}
      onToken={(value) => {
        saveToken(value);
        setToken(value);
      }}
    />
  );
}

function LangToggle({ lang, setLang }: { lang: Lang; setLang: (lang: Lang) => void }) {
  return (
    <button type="button" className="ghost" onClick={() => setLang(lang === 'en' ? 'bn' : 'en')}>
      {lang === 'en' ? 'বাংলা' : 'English'}
    </button>
  );
}

function TokenPrompt({ lang, setLang, onToken }: { lang: Lang; setLang: (lang: Lang) => void; onToken: (token: string) => void }) {
  const [value, setValue] = useState('');
  const t = (bn: string, en: string) => (lang === 'bn' ? bn : en);
  return (
    <main className="login">
      <form
        className="card login-card"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) onToken(value.trim());
        }}
      >
        <div className="row between">
          <h1>{t('অভিযাত্রী সিস্টেম মনিটরিং', 'Abhijatri System Monitoring')}</h1>
          <LangToggle lang={lang} setLang={setLang} />
        </div>
        <p className="muted">
          {t(
            'API সার্ভারের OPS_DASHBOARD_TOKEN দিন। টোকেনটি শুধু এই ট্যাবে থাকে; ট্যাব বন্ধ করলে মুছে যায়।',
            "Enter the API server's OPS_DASHBOARD_TOKEN. It is kept only in this tab and is gone when the tab closes.",
          )}
        </p>
        <label htmlFor="token">{t('টোকেন', 'Token')}</label>
        <input id="token" type="password" autoComplete="off" spellCheck={false} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
        <button type="submit" className="primary">
          {t('খুলুন', 'Open dashboard')}
        </button>
        <p className="muted small">API: {API_BASE}</p>
      </form>
    </main>
  );
}

function Dashboard({
  token,
  lang,
  setLang,
  onSignOut,
}: {
  token: string;
  lang: Lang;
  setLang: (lang: Lang) => void;
  onSignOut: () => void;
}) {
  const t = (bn: string, en: string) => (lang === 'bn' ? bn : en);
  const [days, setDays] = useState<Days>(30);
  const [panels, setPanels] = useState<PanelData[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rollup, setRollup] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<string | null>(null);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof OpsError && err.status === 401) onSignOut();
      else setError(err);
    },
    [onSignOut],
  );

  const load = useCallback(() => {
    setError(null);
    // The catalogue sets the layout; a catalogue failure alone must not hide the data.
    const catalogue = getCatalogue(token).then((c) => c.panels, (err) => (err instanceof OpsError && err.status === 401 ? Promise.reject(err) : []));
    Promise.all([getOverview(token, days), catalogue])
      .then(([overview, entries]) => {
        setPanels(orderByCatalogue(overview.panels, entries));
        setLoadedAt(overview.generated_at);
      })
      .catch(handleError);
  }, [token, days, handleError]);

  useEffect(load, [load]);

  const replacePanel = useCallback((panel: PanelData) => {
    setPanels((current) => current?.map((p) => (p.id === panel.id ? panel : p)) ?? null);
  }, []);

  const doRollup = () => {
    setRollup(t('চলছে…', 'Running…'));
    runRollup(token)
      .then(({ rolled_up }) => {
        setRollup(
          rolled_up.length
            ? t(`রোল-আপ হয়েছে: ${rolled_up.join(', ')}`, `Rolled up: ${rolled_up.join(', ')}`)
            : t('নতুন কোনো দিন নেই।', 'Nothing new to roll up.'),
        );
        load();
      })
      .catch((err) => setRollup(describeError(err, lang)));
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>{t('সিস্টেম মনিটরিং', 'System Monitoring')}</h1>
          <p className="muted small">
            {t('শেষ লোড', 'Loaded')} {formatTime(loadedAt, lang)} · {t('সব সংখ্যা সমষ্টিগত; কোনো ব্যক্তির তথ্য নেই।', 'Aggregates only; no personal data.')}
          </p>
        </div>
        <div className="row">
          <div className="segmented" role="group" aria-label={t('সময়সীমা', 'Range')}>
            {DAY_CHOICES.map((choice) => (
              <button key={choice} type="button" aria-pressed={choice === days} onClick={() => setDays(choice)}>
                {choice} {t('দিন', 'days')}
              </button>
            ))}
          </div>
          <button type="button" className="ghost" onClick={load}>
            {t('রিফ্রেশ', 'Refresh')}
          </button>
          <button type="button" className="ghost" onClick={doRollup}>
            {t('রোল-আপ চালান', 'Run roll-up')}
          </button>
          <LangToggle lang={lang} setLang={setLang} />
          <button type="button" className="ghost" onClick={onSignOut}>
            {t('বের হন', 'Sign out')}
          </button>
        </div>
      </header>
      {rollup && <p className="notice">{rollup}</p>}
      {error !== null && <p className="notice error">{describeError(error, lang)}</p>}
      {panels === null && error === null && <p className="muted">{t('লোড হচ্ছে…', 'Loading…')}</p>}
      <main className="grid">
        {panels?.map((panel) => (
          <Panel key={panel.id} panel={panel} token={token} days={days} lang={lang} onUpdate={replacePanel} onError={handleError} />
        ))}
      </main>
    </div>
  );
}

function Panel({
  panel,
  token,
  days,
  lang,
  onUpdate,
  onError,
}: {
  panel: PanelData;
  token: string;
  days: Days;
  lang: Lang;
  onUpdate: (panel: PanelData) => void;
  onError: (error: unknown) => void;
}) {
  // Each panel refreshes and fails on its own (System-Monitoring-Dashboard 5).
  useEffect(() => {
    const seconds = Math.max(15, panel.refresh_seconds || 60);
    const timer = window.setInterval(() => {
      getPanel(token, panel.id, days).then(onUpdate).catch(onError);
    }, seconds * 1000);
    return () => window.clearInterval(timer);
  }, [panel.id, panel.refresh_seconds, token, days, onUpdate, onError]);

  const t = (bn: string, en: string) => (lang === 'bn' ? bn : en);
  return (
    <section className={`card panel status-${panel.status} ${panel.id === 'visitors' ? 'wide' : ''}`} aria-labelledby={`panel-${panel.id}`}>
      <header className="panel-head">
        <h2 id={`panel-${panel.id}`}>{panel.title[lang]}</h2>
        <span className={`badge status-${panel.status}`}>
          {panel.status === 'ok' ? t('ঠিক আছে', 'ok') : panel.status === 'degraded' ? t('আংশিক', 'degraded') : t('পাওয়া যায়নি', 'unavailable')}
        </span>
      </header>
      {panel.status === 'unavailable' ? (
        <p className="muted">{t('এই প্যানেলের তথ্য এখন পাওয়া যাচ্ছে না।', 'This panel is unavailable right now.')}</p>
      ) : (
        <BlockList blocks={panel.blocks} lang={lang} />
      )}
      {panel.notes.length > 0 && (
        <ul className="notes">
          {panel.notes.map((note) => (
            <li key={note.en}>{note[lang]}</li>
          ))}
        </ul>
      )}
      <footer className="sources muted small">
        {panel.sources.map((source) => (
          <span key={source.name}>
            {source.name}: {formatTime(source.fresh_at, lang)}
          </span>
        ))}
      </footer>
    </section>
  );
}
