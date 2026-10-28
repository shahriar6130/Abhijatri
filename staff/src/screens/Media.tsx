import { useCallback, useEffect, useState } from 'react';
import { decideMedia, listMedia, reviewMediaUrl, type StaffMediaItem } from '../api';
import { errorText } from '../logic';
import type { Lang } from '../types';
import { Notice, makeT } from '../ui';

type Filter = 'rejected' | 'approved' | 'pending';

/**
 * Review photos and videos after their review was decided (API.md 5.20): look at one through a
 * five-minute link and correct its decision. Every change is audited as media.approve / media.reject.
 */
export function Media({ lang }: { lang: Lang }) {
  const t = makeT(lang);
  const [filter, setFilter] = useState<Filter>('rejected');
  const [items, setItems] = useState<StaffMediaItem[] | null>(null);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ tone: 'success' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await listMedia(filter)).items);
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  }, [filter, lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const show = async (item: StaffMediaItem) => {
    try {
      const link = await reviewMediaUrl(item.review_id, item.id);
      setUrls((current) => ({ ...current, [item.id]: link.url }));
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  };

  const decide = async (item: StaffMediaItem, decision: 'approve' | 'reject') => {
    setBusy(item.id);
    try {
      await decideMedia(item.id, decision, decision === 'approve' ? 'media-approved-on-review' : 'media-rejected-on-review');
      setMessage({ tone: 'success', text: decision === 'approve' ? t('অনুমোদিত: এখন রিভিউতে দেখা যাবে।', 'Approved: it now shows on the review.') : t('বাতিল: আর দেখা যাবে না।', 'Rejected: it is no longer shown.') });
      await load();
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="stack">
      <h2>{t('ছবি ও ভিডিও', 'Photos and video')}</h2>
      <p className="small muted">
        {t(
          'অপেক্ষমাণ ছবি/ভিডিও রিভিউর সিদ্ধান্তের সাথে ঠিক হয় (কিউ)। এখানে সিদ্ধান্ত হয়ে যাওয়া ছবি/ভিডিও ঠিক করা যায়; প্রতিটি পরিবর্তন অডিট লগে যায়।',
          'Pending items are decided with their review (Queue). Here you can correct a decided photo or video; every change goes to the audit log.',
        )}
      </p>
      <div className="segmented" role="group">
        {(['rejected', 'approved', 'pending'] as Filter[]).map((option) => (
          <button key={option} type="button" aria-pressed={filter === option} onClick={() => setFilter(option)}>
            {option === 'rejected' ? t('বাতিল', 'Rejected') : option === 'approved' ? t('অনুমোদিত', 'Approved') : t('অপেক্ষমাণ', 'Pending')}
          </button>
        ))}
      </div>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {items && items.length === 0 && <Notice tone="info">{t('কিছু নেই।', 'Nothing here.')}</Notice>}
      <ul className="media-list">
        {items?.map((item) => (
          <li key={item.id} className="media-item content-box">
            {urls[item.id] ? (
              item.kind === 'image' ? (
                <img src={urls[item.id]} alt={item.alt_text} className="media-preview" />
              ) : (
                <video src={urls[item.id]} controls preload="metadata" className="media-preview" />
              )
            ) : (
              <button type="button" onClick={() => void show(item)}>
                {item.kind === 'image' ? t('ছবি দেখুন', 'Show photo') : t('ভিডিও দেখুন', 'Show video')}
              </button>
            )}
            <span className="small">{item.alt_text}</span>
            <span className="small muted">
              <span className="tag">{item.state}</span> {t('রিভিউ', 'Review')}: {item.review_status} · {item.review_id.slice(0, 8)}
            </span>
            {item.state === 'rejected' && (
              <button type="button" className="primary" disabled={busy === item.id} onClick={() => void decide(item, 'approve')}>
                {t('অনুমোদন করুন', 'Approve')}
              </button>
            )}
            {item.state === 'approved' && (
              <button type="button" disabled={busy === item.id} onClick={() => void decide(item, 'reject')}>
                {t('বাতিল করুন', 'Reject')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
