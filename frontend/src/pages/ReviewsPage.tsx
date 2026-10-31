import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MessageSquareText } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import { listAllDestinations } from '../api/destinations';
import { useApiResource } from '../hooks/useApiResource';
import { EmptyState, ErrorState, LoadingState } from '../components/common/StatusViews';
import { GuestReviewForm, type SubmittedReview } from '../components/reviews/GuestReviewForm';
import { ReceiptPanel } from '../components/reviews/ReceiptPanel';
import { ReceiptStatusPanel } from '../components/reviews/ReceiptStatusPanel';
import { RemovalRequestForm } from '../components/reviews/RemovalRequestForm';

export const ReviewsPage: React.FC = () => {
  const { t } = useLanguage();
  const [searchParams] = useSearchParams();
  const [submitted, setSubmitted] = useState<SubmittedReview | null>(null);
  const { data: destinations, error, loading, reload } = useApiResource((signal) => listAllDestinations(signal), []);

  return (
    <div className="flex flex-col gap-6 pb-12 max-w-3xl mx-auto">
      <div>
        <div className="flex items-center gap-2 text-forest-primary dark:text-neon-lime text-xs font-bold uppercase tracking-wider mb-1">
          <MessageSquareText size={16} aria-hidden="true" />
          <span>{t('অতিথি রিভিউ', 'Guest review')}</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-bold font-title text-on-surface dark:text-on-dark tracking-tight">
          {t('আপনার ভ্রমণ অভিজ্ঞতা লিখুন', 'Share your travel experience')}
        </h1>
        <p className="text-sm text-on-surface-variant dark:text-on-dark-muted font-body mt-1">
          {t(
            'অ্যাকাউন্ট ছাড়াই রিভিউ দিন। মডারেশনের পর প্রকাশিত হবে, আর রিসিপ্ট দিয়ে অবস্থা দেখা বা প্রত্যাহার করা যাবে।',
            'No account needed. Reviews are published after moderation, and your receipt lets you check status or withdraw.',
          )}
        </p>
      </div>

      {submitted ? (
        <ReceiptPanel review={submitted} onDone={() => setSubmitted(null)} />
      ) : loading ? (
        <LoadingState />
      ) : error !== null ? (
        <ErrorState error={error} onRetry={reload} />
      ) : destinations && destinations.length > 0 ? (
        <GuestReviewForm
          destinations={destinations}
          initialDestinationId={searchParams.get('destination')}
          onSubmitted={setSubmitted}
        />
      ) : (
        <EmptyState title={t('রিভিউ দেওয়ার মতো কোনো প্রকাশিত গন্তব্য নেই', 'No published destinations to review yet')} />
      )}

      <ReceiptStatusPanel />
      <RemovalRequestForm />
    </div>
  );
};
