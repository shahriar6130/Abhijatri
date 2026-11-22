import React from 'react';
import { Info, X } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useOfflinePacks } from '../../hooks/useOfflinePacks';
import { dismissNotice } from '../../offline/packManager';
import { pick } from '../../utils/format';

/** Tells the traveller a downloaded pack was removed because the server says it is gone (guideline 5.3). */
export const PackNotices: React.FC = () => {
  const { language, t } = useLanguage();
  const { notices } = useOfflinePacks();
  if (notices.length === 0) return null;
  return (
    <div className="w-full bg-muted text-foreground border-b border-border">
      {notices.map((n) => {
        const name = pick(language, n.name_bn, n.name_en) || t('একটি গন্তব্য', 'A destination');
        return (
          <div key={n.destinationId} role="status" className="max-w-7xl mx-auto px-4 py-2 flex items-start gap-2 text-sm">
            <Info size={16} className="shrink-0 mt-0.5" aria-hidden="true" />
            <span className="flex-1">
              {n.why === 'withdrawn'
                ? t(`${name} প্রত্যাহার করা হয়েছে, তাই এর অফলাইন প্যাক মুছে ফেলা হয়েছে।`, `${name} has been withdrawn, so its offline pack was removed.`)
                : t(`${name} আর প্রকাশিত নেই, তাই এর অফলাইন প্যাক মুছে ফেলা হয়েছে।`, `${name} is no longer published, so its offline pack was removed.`)}
            </span>
            <button
              type="button"
              onClick={() => dismissNotice(n.destinationId)}
              aria-label={t('বার্তাটি বন্ধ করুন', 'Dismiss')}
              className="min-w-11 min-h-11 -my-2 flex items-center justify-center rounded-full hover:bg-surface-container"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
