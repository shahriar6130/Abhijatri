/**
 * Client-side checks for review photos and video (Review.md 8; amendment A4 approved without
 * transcoding, 27 Oct 2026). Any signed-in member may attach media; guests stay text-only.
 *
 * These checks only give fast feedback. Browser metadata and MIME types are untrusted: the
 * server re-reads the real file, re-encodes photos without EXIF/GPS, checks the video's codec and
 * length and strips its metadata before a moderator sees anything (API.md 5.20).
 */

export const MAX_PHOTOS_PER_REVIEW = 5;
export const MAX_VIDEOS_PER_REVIEW = 1;
export const MAX_PHOTO_BYTES = 8 * 1024 * 1024; // 8 MiB
export const MAX_VIDEO_BYTES = 50 * 1024 * 1024; // 50 MiB
export const MAX_PHOTO_PIXELS = 20_000_000; // 20 megapixels
export const MAX_VIDEO_SECONDS = 60;
export const ACCEPTED_PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const;
export const ACCEPTED_VIDEO_TYPES = ['video/mp4'] as const;
export const ALT_TEXT_MAX = 250;
export const CAPTION_MAX = 300;

export type MediaKind = 'image' | 'video';
export type PhotoProblem = 'TYPE' | 'TOO_LARGE' | 'TOO_MANY' | 'TOO_MANY_PIXELS' | 'TOO_LONG';

export interface PhotoCandidate {
  name: string;
  type: string;
  size: number;
}

export interface MediaCheck<T extends PhotoCandidate> {
  accepted: { file: T; kind: MediaKind }[];
  rejected: { file: T; problem: PhotoProblem }[];
}

export function mediaKind(type: string): MediaKind | null {
  if ((ACCEPTED_PHOTO_TYPES as readonly string[]).includes(type)) return 'image';
  if ((ACCEPTED_VIDEO_TYPES as readonly string[]).includes(type)) return 'video';
  return null;
}

/** Splits newly chosen files into accepted and rejected, respecting the per-review limits. */
export function checkMediaFiles<T extends PhotoCandidate>(
  files: T[],
  attached: { images: number; videos: number },
): MediaCheck<T> {
  const result: MediaCheck<T> = { accepted: [], rejected: [] };
  const count = { image: attached.images, video: attached.videos };
  for (const file of files) {
    const kind = mediaKind(file.type);
    if (kind === null) {
      result.rejected.push({ file, problem: 'TYPE' });
    } else if (file.size > (kind === 'image' ? MAX_PHOTO_BYTES : MAX_VIDEO_BYTES)) {
      result.rejected.push({ file, problem: 'TOO_LARGE' });
    } else if (count[kind] >= (kind === 'image' ? MAX_PHOTOS_PER_REVIEW : MAX_VIDEOS_PER_REVIEW)) {
      result.rejected.push({ file, problem: 'TOO_MANY' });
    } else {
      count[kind] += 1;
      result.accepted.push({ file, kind });
    }
  }
  return result;
}

export function exceedsPixelLimit(width: number, height: number): boolean {
  return width * height > MAX_PHOTO_PIXELS;
}

export function exceedsVideoLength(seconds: number): boolean {
  return seconds > MAX_VIDEO_SECONDS + 0.5; // encoders round the last frame; the server allows the same
}

/** Every attached photo or video needs a description (PF 20) and the uploader's ownership declaration. */
export function photoMetadataComplete(photo: { altText: string; ownershipDeclared: boolean }): boolean {
  const alt = photo.altText.trim();
  return alt.length > 0 && alt.length <= ALT_TEXT_MAX && photo.ownershipDeclared;
}
