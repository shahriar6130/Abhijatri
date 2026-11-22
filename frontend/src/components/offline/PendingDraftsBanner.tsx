import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { FileText, X } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useOnlineStatus } from '../../hooks/useNetworkState';
import { formatNumber } from '../../utils/format';

/** Shown once per page load at most, unless the connection drops and returns again. */
let shownThisLoad = false;

/**
 * "You have N unsent review drafts" when the connection returns, or on the first online page of a
 * visit (owner decision 9 Nov 2026; Offline-Frontend-Guideline 6.4). It only links to the Write page:
 * nothing is sent automatically (RV 7.3). Not shown on the Write page, which lists the drafts itself.
 */
export const PendingDraftsBanner: React.FC<{ count: number }> = ({ count }) => {
  const { language, t } = useLanguage();
  const online = useOnlineStatus();
  const { pathname } = useLocation();
  const [visible, setVisible] = useState(!shownThisLoad);

  useEffect(() => {
    const back = () => setVisible(true); // the connection returned: tell again
    window.addEventListener('online', back);
    return () => window.removeEventListener('online', back);
  }, []);

  const show = visible && online && count > 0 && !pathname.startsWith('/reviews/write');
  useEffect(() => {
    if (show) shownThisLoad = true;
  }, [show]);
  if (!show) return null;

  const n = formatNumber(count, language);
  return (
    <div className="w-full bg-primary/10 text-foreground border-b border-primary/30">
      <div role="status" className="max-w-7xl mx-auto px-4 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <FileText size={16} className="shrink-0" aria-hidden="true" />
        <span className="flex-1 min-w-48">
          {t(
            `এই ডিভাইসে আপনার ${n}টি না পাঠানো রিভিউ খসড়া আছে। কিছুই নিজে থেকে পাঠানো হয় না।`,
            `You have ${n} unsent review draft${count === 1 ? '' : 's'} on this device. Nothing is sent by itself.`,
          )}
        </span>
        <Link to="/reviews/write" onClick={() => setVisible(false)} className="font-semibold underline underline-offset-2 min-h-11 inline-flex items-center">
          {t('দেখুন ও পাঠান', 'Review and send')}
        </Link>
        <button
          type="button"
          onClick={() => setVisible(false)}
          aria-label={t('বার্তাটি বন্ধ করুন', 'Dismiss')}
          className="min-w-11 min-h-11 -my-2 flex items-center justify-center rounded-full hover:bg-primary/15"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};
