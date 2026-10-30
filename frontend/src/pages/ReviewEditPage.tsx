import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { ApiError } from '../api/client';
import { editMemberReview, getReview } from '../api/reviews';
import { Notice, linkClass } from '../components/auth/AccountUi';
import { LoadingState, describeError } from '../components/common/StatusViews';
import { ReviewEditForm } from '../components/reviews/ReviewEditForm';
import { StatusChip } from '../components/reviews/StatusChip';
import { useLanguage } from '../context/LanguageContext';
import { useSession } from '../context/SessionContext';
import type { ReviewDetail, ReviewEditChanges } from '../types';
import { canEdit, valuesFromDetail } from '../utils/reviewAuthor';

/** Edit one of the signed-in author's unpublished reviews (PENDING or CHANGES_REQUESTED). */
export const ReviewEditPage: React.FC = () => {
  const { t } = useLanguage();
  const { session, status: sessionStatus } = useSession();
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await getReview(id));
    } catch (err: unknown) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    if (session.kind === 'member') void load();
  }, [session.kind, load]);

  const original = useMemo(() => (detail ? valuesFromDetail(detail) : null), [detail]);

  const save = async (changes: ReviewEditChanges) => {
    if (!detail) return;
    const result = await editMemberReview(detail.id, detail.version, changes);
    navigate(`/account/reviews/${detail.id}`, {
      state: { saved: t(`সংরক্ষিত হয়েছে। এখন সংস্করণ ${result.revision}; মডারেটরের পর্যালোচনার অপেক্ষায়।`, `Saved as version ${result.revision}. It is waiting for moderation again.`) },
    });
  };

  if (sessionStatus === 'loading') return <LoadingState />;
  if (session.kind !== 'member') {
    return (
      <div className="max-w-xl mx-auto px-4 py-10">
        <Notice tone="info">{t('সম্পাদনা করতে সাইন ইন করুন।', 'Sign in to edit a review.')} <Link to="/login" className={linkClass}>{t('সাইন ইন', 'Sign in')}</Link></Notice>
      </div>
    );
  }
  if (loading) return <LoadingState />;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="max-w-xl mx-auto px-4 py-10 flex flex-col gap-3">
        <Notice tone="error">{t('এই রিভিউটি পাওয়া যায়নি।', 'This review was not found.')}</Notice>
        <Link to="/account/reviews" className={linkClass}>{t('আমার রিভিউয়ে ফিরুন', 'Back to my reviews')}</Link>
      </div>
    );
  }
  if (error !== null || !detail || !original) {
    return (
      <div className="max-w-xl mx-auto px-4 py-10 flex flex-col gap-3">
        <Notice tone="error">{describeError(error, t)}</Notice>
        <button type="button" onClick={() => void load()} className="self-start min-h-[44px] px-4 rounded-full border text-xs font-bold">{t('আবার চেষ্টা করুন', 'Retry')}</button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
      <Link to={`/account/reviews/${detail.id}`} className={`${linkClass} inline-flex items-center gap-1 text-sm`}><ArrowLeft size={14} aria-hidden="true" />{t('রিভিউতে ফিরুন', 'Back to the review')}</Link>
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <h1 className="text-2xl font-bold font-title">{t('রিভিউ সম্পাদনা', 'Edit review')}</h1>
        <StatusChip status={detail.status} />
      </div>
      {canEdit(detail.status) ? (
        <ReviewEditForm
          mode="member"
          original={original}
          onSave={save}
          onCancel={() => navigate(`/account/reviews/${detail.id}`)}
          onReload={() => void load()}
          intro={
            detail.status === 'CHANGES_REQUESTED' ? (
              <Notice tone="info">
                {t('মডারেটর আপনার রিভিউ ফেরত পাঠিয়েছেন।', 'A moderator sent your review back.')}
                {detail.decision_reason && <> {t('কারণ', 'Reason')}: <span className="font-en font-semibold">{detail.decision_reason}</span></>}
              </Notice>
            ) : undefined
          }
        />
      ) : (
        <Notice tone="error">{t('রিভিউটির বর্তমান অবস্থায় আর সম্পাদনা করা যাবে না।', 'This review can no longer be edited in its current state.')}</Notice>
      )}
    </div>
  );
};
