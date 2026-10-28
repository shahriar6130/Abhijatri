import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ImagePlus, Lock, Trash2 } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useSession } from '../../context/SessionContext';
import {
  ACCEPTED_PHOTO_TYPES,
  ACCEPTED_VIDEO_TYPES,
  ALT_TEXT_MAX,
  CAPTION_MAX,
  MAX_PHOTOS_PER_REVIEW,
  MAX_VIDEOS_PER_REVIEW,
  checkMediaFiles,
  exceedsPixelLimit,
  exceedsVideoLength,
  type MediaKind,
  type PhotoProblem,
} from '../../utils/reviewPhotos';

export interface ReviewPhoto {
  id: string;
  kind: MediaKind;
  file: File;
  previewUrl: string;
  altText: string;
  caption: string;
  ownershipDeclared: boolean;
}

const PROBLEM_TEXT: Record<PhotoProblem, [string, string]> = {
  TYPE: ['শুধু JPEG, PNG, WebP ছবি বা MP4 ভিডিও দেওয়া যাবে।', 'Only JPEG, PNG or WebP photos and MP4 video are allowed.'],
  TOO_LARGE: ['ছবি সর্বোচ্চ ৮ MiB, ভিডিও সর্বোচ্চ ৫০ MiB।', 'Photos can be at most 8 MiB and video at most 50 MiB.'],
  TOO_MANY: ['একটি রিভিউতে সর্বোচ্চ ৫টি ছবি ও ১টি ভিডিও।', 'A review can have at most 5 photos and 1 video.'],
  TOO_MANY_PIXELS: ['ছবির রেজোলিউশন সর্বোচ্চ ২০ মেগাপিক্সেল।', 'Photo resolution can be at most 20 megapixels.'],
  TOO_LONG: ['ভিডিও সর্বোচ্চ ৬০ সেকেন্ড।', 'Video can be at most 60 seconds long.'],
};

/** Why the server refused an uploaded file (API.md 5.20 field codes). */
export const SERVER_MEDIA_TEXT: Record<string, [string, string]> = {
  ...PROBLEM_TEXT,
  BROKEN: ['ফাইলটি পড়া যায়নি বা নষ্ট।', 'The file could not be read or is damaged.'],
  VIDEO_CODEC: [
    'ভিডিওটি H.264 (MP4) নয়। ফোনে "Most Compatible"/H.264 বেছে নিয়ে আবার রেকর্ড বা এক্সপোর্ট করুন।',
    'The video is not H.264 MP4. Record or export it again with "Most Compatible"/H.264.',
  ],
  NOT_UPLOADED: ['ফাইলটি পৌঁছায়নি। আবার চেষ্টা করুন।', 'The file did not arrive. Try again.'],
};

async function pixelCount(file: File): Promise<{ width: number; height: number } | null> {
  try {
    const bitmap = await createImageBitmap(file);
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return size;
  } catch {
    return null; // undecodable here; the server decides
  }
}

function videoSeconds(url: string): Promise<number | null> {
  return new Promise((resolve) => {
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => resolve(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => resolve(null); // e.g. a codec this browser cannot read; the server decides
    video.src = url;
  });
}

/**
 * Photos and one video for a review (Review.md 8 and amendment A4). Any signed-in member may
 * attach them (owner, 27 Oct 2026); guests write text-only reviews and see why. The files are
 * uploaded after the review is created (`uploadReviewMedia`), then checked by the server and
 * shown only after a moderator approves them.
 */
export const ReviewPhotos: React.FC<{
  photos: ReviewPhoto[];
  onChange: (next: ReviewPhoto[]) => void;
}> = ({ photos, onChange }) => {
  const { t } = useLanguage();
  const { session } = useSession();
  const [problems, setProblems] = useState<string[]>([]);
  const latest = useRef(photos);
  latest.current = photos;

  // Release preview URLs when the component goes away.
  useEffect(() => () => latest.current.forEach((p) => URL.revokeObjectURL(p.previewUrl)), []);

  if (session.kind !== 'member') {
    return (
      <div className="p-4 rounded-xl border border-dashed border-surface-muted dark:border-dark-surface-2 flex gap-3 text-sm">
        <Lock size={18} className="shrink-0 mt-0.5 text-on-surface-variant dark:text-on-dark-muted" aria-hidden="true" />
        <div className="flex flex-col gap-1">
          <p className="font-semibold text-on-surface dark:text-on-dark">{t('ছবি ও ভিডিও সদস্যদের জন্য', 'Photos and video are for members')}</p>
          <p className="text-xs text-on-surface-variant dark:text-on-dark-muted">
            {t(
              'অতিথি রিভিউ শুধু লেখায় হয়। ছবি বা ভিডিও যোগ করতে সাইন ইন করুন।',
              'Guest reviews are text only. Sign in to add photos or a video.',
            )}{' '}
            <Link to="/login" className="underline underline-offset-2 text-forest-primary dark:text-neon-lime">
              {t('সাইন ইন', 'Sign in')}
            </Link>
          </p>
        </div>
      </div>
    );
  }

  const images = photos.filter((p) => p.kind === 'image').length;
  const videos = photos.length - images;

  const addFiles = async (list: FileList | null) => {
    if (!list) return;
    const { accepted, rejected } = checkMediaFiles(Array.from(list), { images, videos });
    const messages = rejected.map(({ file, problem }) => `${file.name}: ${t(...PROBLEM_TEXT[problem])}`);
    const added: ReviewPhoto[] = [];
    for (const { file, kind } of accepted) {
      const previewUrl = URL.createObjectURL(file);
      if (kind === 'image') {
        const size = await pixelCount(file);
        if (size && exceedsPixelLimit(size.width, size.height)) {
          messages.push(`${file.name}: ${t(...PROBLEM_TEXT.TOO_MANY_PIXELS)}`);
          URL.revokeObjectURL(previewUrl);
          continue;
        }
      } else {
        const seconds = await videoSeconds(previewUrl);
        if (seconds !== null && exceedsVideoLength(seconds)) {
          messages.push(`${file.name}: ${t(...PROBLEM_TEXT.TOO_LONG)}`);
          URL.revokeObjectURL(previewUrl);
          continue;
        }
      }
      added.push({ id: crypto.randomUUID(), kind, file, previewUrl, altText: '', caption: '', ownershipDeclared: false });
    }
    setProblems(messages);
    onChange([...photos, ...added]);
  };

  const update = (id: string, patch: Partial<ReviewPhoto>) =>
    onChange(photos.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  const remove = (id: string) => {
    const photo = photos.find((p) => p.id === id);
    if (photo) URL.revokeObjectURL(photo.previewUrl);
    onChange(photos.filter((p) => p.id !== id));
  };

  const canAdd = images < MAX_PHOTOS_PER_REVIEW || videos < MAX_VIDEOS_PER_REVIEW;
  const accept = [
    ...(images < MAX_PHOTOS_PER_REVIEW ? ACCEPTED_PHOTO_TYPES : []),
    ...(videos < MAX_VIDEOS_PER_REVIEW ? ACCEPTED_VIDEO_TYPES : []),
  ].join(',');

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
        {t(
          `ছবি ও ভিডিও (ঐচ্ছিক: সর্বোচ্চ ${MAX_PHOTOS_PER_REVIEW}টি ছবি, ১টি ভিডিও ৬০ সেকেন্ড পর্যন্ত)`,
          `Photos and video (optional: up to ${MAX_PHOTOS_PER_REVIEW} photos and 1 video of up to 60 seconds)`,
        )}
      </legend>
      <p className="text-xs text-on-surface-variant dark:text-on-dark-muted -mt-1">
        {t(
          'ছবি ও ভিডিও থেকে অবস্থান ও ক্যামেরার তথ্য সরিয়ে ফেলা হয় এবং মডারেটর অনুমোদনের পর প্রকাশিত হয়। ভিডিও MP4 (H.264) হতে হবে। অন্যের মুখ বা ব্যক্তিগত তথ্য থাকলে দেবেন না।',
          'Location and camera data are removed, and photos and video are published only after a moderator approves them. Video must be MP4 (H.264). Do not upload anything showing other people’s faces or personal details.',
        )}
      </p>

      {canAdd && (
        <label className="self-start inline-flex items-center gap-2 min-h-[44px] px-4 rounded-full bg-surface-sage dark:bg-dark-surface-2 text-forest-primary dark:text-neon-lime text-xs font-bold font-title cursor-pointer focus-within:ring-2 focus-within:ring-forest-primary">
          <ImagePlus size={16} aria-hidden="true" />
          {t('ছবি বা ভিডিও যোগ করুন', 'Add photos or video')}
          <input
            type="file"
            accept={accept}
            multiple
            className="sr-only"
            onChange={(e) => {
              void addFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </label>
      )}

      {problems.length > 0 && (
        <ul role="alert" className="text-xs text-error-alert dark:text-red-400 list-disc pl-5">
          {problems.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}

      <ul className="flex flex-col gap-3">
        {photos.map((photo, index) => (
          <li key={photo.id} className="flex flex-col sm:flex-row gap-3 p-3 rounded-xl bg-surface-container/50 dark:bg-dark-surface-2">
            {photo.kind === 'image' ? (
              <img src={photo.previewUrl} alt="" className="w-24 h-24 object-cover rounded-lg shrink-0" />
            ) : (
              <video src={photo.previewUrl} controls preload="metadata" className="w-full sm:w-40 h-24 rounded-lg shrink-0 bg-black" />
            )}
            <div className="flex-1 flex flex-col gap-2">
              <label className="flex flex-col gap-1 text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
                {photo.kind === 'image'
                  ? t(`ছবি ${index + 1}-এর বিবরণ (দৃষ্টিপ্রতিবন্ধীদের জন্য, আবশ্যক)`, `Describe photo ${index + 1} (for screen readers, required)`)
                  : t('ভিডিওর বিবরণ (আবশ্যক)', 'Describe the video (required)')}
                <input
                  value={photo.altText}
                  maxLength={ALT_TEXT_MAX}
                  onChange={(e) => update(photo.id, { altText: e.target.value })}
                  className="px-3 min-h-[40px] rounded-lg border border-surface-muted/50 dark:border-dark-surface-1 bg-white dark:bg-dark-surface-1 text-sm font-normal text-on-surface dark:text-on-dark"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-bold text-on-surface-variant dark:text-on-dark-muted">
                {t('ক্যাপশন (ঐচ্ছিক)', 'Caption (optional)')}
                <input
                  value={photo.caption}
                  maxLength={CAPTION_MAX}
                  onChange={(e) => update(photo.id, { caption: e.target.value })}
                  className="px-3 min-h-[40px] rounded-lg border border-surface-muted/50 dark:border-dark-surface-1 bg-white dark:bg-dark-surface-1 text-sm font-normal text-on-surface dark:text-on-dark"
                />
              </label>
              <label className="flex items-start gap-2 text-xs text-on-surface dark:text-on-dark">
                <input
                  type="checkbox"
                  checked={photo.ownershipDeclared}
                  onChange={(e) => update(photo.id, { ownershipDeclared: e.target.checked })}
                  className="mt-0.5 h-4 w-4 accent-forest-primary dark:accent-neon-lime"
                />
                {photo.kind === 'image'
                  ? t('ছবিটি আমি নিজে তুলেছি এবং প্রকাশের অধিকার আমার আছে।', 'I took this photo and have the right to publish it.')
                  : t('ভিডিওটি আমি নিজে করেছি এবং প্রকাশের অধিকার আমার আছে।', 'I made this video and have the right to publish it.')}
              </label>
            </div>
            <button
              type="button"
              onClick={() => remove(photo.id)}
              aria-label={photo.kind === 'image' ? t(`ছবি ${index + 1} সরান`, `Remove photo ${index + 1}`) : t('ভিডিও সরান', 'Remove the video')}
              className="self-start min-w-[40px] min-h-[40px] flex items-center justify-center rounded-full text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/40"
            >
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </fieldset>
  );
};
