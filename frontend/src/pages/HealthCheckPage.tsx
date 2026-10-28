import React, { useState, useEffect } from 'react';
import { 
  Activity, 
  CheckCircle2, 
  XCircle, 
  RefreshCw, 
  Server, 
  Database, 
  Globe, 
  Zap, 
  AlertCircle
} from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { checkBackendHealth, isAllowedBackendUrl } from '../api/health';
import { HealthStatus } from '../types';
import { DISPLAY_TIME_ZONE, formatNumber } from '../utils/format';

export const HealthCheckPage: React.FC = () => {
  const { language, t } = useLanguage();
  const [backendUrl, setBackendUrl] = useState<string>(
    import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [healthResult, setHealthResult] = useState<HealthStatus | null>(null);

  const runTest = async (urlToTest?: string) => {
    const target = urlToTest || backendUrl;
    if (!isAllowedBackendUrl(target)) {
      setHealthResult({
        status: 'blocked',
        error: t(
          'এই URL অনুমোদিত তালিকায় নেই, তাই কোনো অনুরোধ পাঠানো হয়নি। HTTPS ব্যবহার করুন এবং হোস্টটি frontend/.env-এর VITE_ALLOWED_BACKEND_HOSTS-এ যোগ করুন।',
          'This URL is not on the allow-list, so no request was sent. Use HTTPS and add the host to VITE_ALLOWED_BACKEND_HOSTS in frontend/.env.',
        ),
        timestamp: new Date().toISOString(),
        urlChecked: target,
      });
      return;
    }

    setLoading(true);
    try {
      const res = await checkBackendHealth(target);
      setHealthResult(res);
    } catch (err: unknown) {
      setHealthResult({
        status: 'error',
        error: err instanceof Error ? err.message : String(err),
        timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    runTest();
  }, []);

  return (
    <div className="flex flex-col gap-6 pb-12 max-w-4xl mx-auto">
      {/* Title */}
      <div>
        <div className="flex items-center gap-2 text-forest-primary dark:text-neon-lime text-xs font-bold uppercase font-en tracking-wider mb-1">
          <Activity size={16} />
          <span>{t('লাইভ ব্যাকএন্ড ডায়াগনস্টিক', 'Live Backend Diagnostic Console')}</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark tracking-tight">
          {t('সিস্টেম হেলথ চেক ও এপিআই কানেকশন', 'API Health & Connectivity Verification')}
        </h1>
        <p className="text-xs sm:text-sm text-on-surface-variant dark:text-on-dark-muted font-body mt-1">
          {t(
            'ফ্রন্টএন্ড থেকে সরাসরি ফাস্টএপিআই ব্যাকএন্ডের GET /api/v1/health এবং GET /api/health যাচাই করুন।',
            'Verify real-time HTTP connectivity, response latency, and database readiness with the FastAPI backend.'
          )}
        </p>
      </div>

      {/* Target URL Config Card */}
      <div className="tonal-card p-6 flex flex-col gap-4">
        <h2 className="text-sm font-bold font-en uppercase text-on-surface-variant dark:text-on-dark-muted">
          {t('যে সার্ভার পরীক্ষা করবেন', 'Server to check')}
        </h2>
        
        <div className="flex flex-col sm:flex-row items-center gap-3">
          <div className="relative flex-1 w-full">
            <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant" size={16} />
            <input
              type="text"
              value={backendUrl}
              onChange={(e) => setBackendUrl(e.target.value)}
              placeholder={t('যেমন http://localhost:8000', 'e.g. http://localhost:8000')}
              className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-surface-sage/40 dark:bg-dark-surface-2 border border-surface-muted/40 text-sm font-en font-medium text-on-surface dark:text-on-dark focus:ring-1 focus:ring-forest-primary dark:focus:ring-neon-lime"
            />
          </div>

          <button
            onClick={() => runTest(backendUrl)}
            disabled={loading}
            className="w-full sm:w-auto px-6 py-2.5 rounded-full bg-forest-primary text-white dark:bg-neon-lime dark:text-dark-bg-base text-xs font-bold font-en flex items-center justify-center gap-2 hover:opacity-90 active:scale-95 transition-all shadow-sm"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            <span>{loading ? t('যাচাই হচ্ছে…', 'Checking…') : t('পরীক্ষা করুন', 'Check now')}</span>
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-on-surface-variant dark:text-on-dark-muted font-en">
          <span>{t('দ্রুত বেছে নিন:', 'Quick presets:')}</span>
          <button
            onClick={() => { setBackendUrl('http://localhost:8000'); runTest('http://localhost:8000'); }}
            className="px-2.5 py-1 rounded-md bg-surface-sage dark:bg-dark-surface-2 hover:bg-surface-container transition-colors"
          >
            Local (http://localhost:8000)
          </button>
          <button
            onClick={() => { setBackendUrl('/api'); runTest('/api'); }}
            className="px-2.5 py-1 rounded-md bg-surface-sage dark:bg-dark-surface-2 hover:bg-surface-container transition-colors"
          >
            {t('ডেভ প্রক্সি (/api)', 'Dev proxy (/api)')}
          </button>
        </div>
      </div>

      {/* Results Display */}
      {healthResult && (
        <div className="tonal-card p-6 flex flex-col gap-6">
          <div className="flex items-center justify-between border-b border-surface-muted/30 dark:border-dark-surface-2 pb-4">
            <div className="flex items-center gap-3">
              {healthResult.status === 'ok' ? (
                <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                  <CheckCircle2 size={24} />
                </div>
              ) : (
                <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-950/60 text-red-600 dark:text-red-400 flex items-center justify-center">
                  <XCircle size={24} />
                </div>
              )}
              <div>
                <h3 className="font-bold text-lg font-title text-on-surface dark:text-on-dark">
                  {healthResult.status === 'ok'
                    ? t('ব্যাকএন্ড সার্ভিস সচল ও কানেক্টেড!', 'Backend Service is Live & Connected!')
                    : healthResult.status === 'blocked'
                      ? t('URL অনুমোদিত নয় (পরীক্ষা করা হয়নি)', 'URL not allowed (not tested)')
                      : t('কানেকশন ব্যর্থ হয়েছে (Unreachable)', 'Backend Service Unreachable')}
                </h3>
                <p className="text-xs text-on-surface-variant dark:text-on-dark-muted font-en">
                  {t('পরীক্ষিত ঠিকানা', 'Checked')}: <span lang="en">{healthResult.urlChecked}</span>
                </p>
                {healthResult.status !== 'ok' && healthResult.error && (
                  <p role="alert" className="mt-1 text-xs text-red-700 dark:text-red-300">
                    {healthResult.error}
                  </p>
                )}
              </div>
            </div>

            {healthResult.latencyMs !== undefined && (
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-xs font-en font-bold text-forest-primary dark:text-neon-lime">
                <Zap size={13} />
                <span>{t(`সাড়া দিতে ${formatNumber(healthResult.latencyMs, language)} মিলিসেকেন্ড`, `${healthResult.latencyMs} ms response`)}</span>
              </div>
            )}
          </div>

          {/* Diagnostic Details Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-3.5 rounded-xl bg-canvas-light dark:bg-dark-surface-2 border border-surface-muted/20 flex flex-col gap-1">
              <div className="flex items-center gap-1.5 text-xs text-on-surface-variant font-en">
                <Server size={14} />
                <span>{t('সার্ভার:', 'Server:')}</span>
              </div>
              <span className={`text-base font-bold font-en capitalize ${
                healthResult.status === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
              }`}>
                {healthResult.status}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-canvas-light dark:bg-dark-surface-2 border border-surface-muted/20 flex flex-col gap-1">
              <div className="flex items-center gap-1.5 text-xs text-on-surface-variant font-en">
                <Database size={14} />
                <span>{t('ডেটাবেস:', 'Database:')}</span>
              </div>
              <span className="text-xs font-semibold font-en text-on-surface dark:text-on-dark">
                {healthResult.database || 'Unverified'}
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-canvas-light dark:bg-dark-surface-2 border border-surface-muted/20 flex flex-col gap-1">
              <div className="flex items-center gap-1.5 text-xs text-on-surface-variant font-en">
                <Activity size={14} />
                <span>{t('যাচাইয়ের সময়:', 'Checked at:')}</span>
              </div>
              <span className="text-xs font-en text-on-surface-variant dark:text-on-dark-muted">
                {healthResult.timestamp ? new Intl.DateTimeFormat(language === 'bn' ? 'bn-BD' : 'en-GB', { timeStyle: 'medium', timeZone: DISPLAY_TIME_ZONE }).format(new Date(healthResult.timestamp)) : ''}
              </span>
            </div>
          </div>

          {/* Error & Guidance Notice if offline */}
          {healthResult.status !== 'ok' && (
            <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 flex items-start gap-3 text-xs text-red-800 dark:text-red-200">
              <AlertCircle size={18} className="shrink-0 mt-0.5 text-red-600" />
              <div className="flex flex-col gap-1">
                <span className="font-bold">{t('সমস্যা সমাধানের টিপস', 'Troubleshooting')}</span>
                <span>{t('১. লোকাল সার্ভার পরীক্ষা করলে backend/ ফোল্ডারে সার্ভারটি চালু আছে কিনা দেখুন:', '1. For a local server, make sure it is running in backend/:')} <code lang="en">uv run uvicorn app.main:app --port 8000</code></span>
                <span>{t('২. ক্লাউড সার্ভারের জন্য তার URL উপরে বসিয়ে "পরীক্ষা করুন" চাপুন।', '2. For a cloud server, paste its URL above and press "Check now".')}</span>
                <span>{t('৩. সার্ভারের CORS_ALLOWED_ORIGINS-এ এই সাইটের ঠিকানা থাকতে হবে, যেমন', "3. The server's CORS_ALLOWED_ORIGINS must include this site's address, e.g.")} <code lang="en">http://localhost:5173</code></span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Contract Snapshot of Key Backend Endpoints */}
      <div className="tonal-card p-6 flex flex-col gap-4">
        <h3 className="font-bold text-sm font-en uppercase text-on-surface-variant dark:text-on-dark-muted">
          {t('প্রধান API ঠিকানা (v1)', 'Main API endpoints (v1)')}
        </h3>
        <div className="divide-y divide-surface-muted/20 text-xs font-en">
          <div className="py-2.5 flex items-center justify-between">
            <span className="font-mono text-emerald-700 dark:text-emerald-400 font-bold">GET /api/v1/health</span>
            <span className="text-on-surface-variant">{t('সার্ভার চালু আছে কিনা', 'Is the server running')}</span>
          </div>
          <div className="py-2.5 flex items-center justify-between">
            <span className="font-mono text-emerald-700 dark:text-emerald-400 font-bold">GET /api/v1/health/ready</span>
            <span className="text-on-surface-variant">{t('ডেটাবেস প্রস্তুত কিনা', 'Is the database ready')}</span>
          </div>
          <div className="py-2.5 flex items-center justify-between">
            <span className="font-mono text-blue-700 dark:text-blue-400 font-bold">POST /api/v1/reviews/guest</span>
            <span className="text-on-surface-variant">{t('অতিথির রিভিউ জমা', 'Guest review submission')}</span>
          </div>
          <div className="py-2.5 flex items-center justify-between">
            <span className="font-mono text-purple-700 dark:text-purple-400 font-bold">GET /api/v1/destinations/{'{id}'}/reviews</span>
            <span className="text-on-surface-variant">{t('প্রকাশিত রিভিউ', 'Published reviews')}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
