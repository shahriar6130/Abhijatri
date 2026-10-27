import { describe, expect, it } from 'vitest';
import {
  MAX_PHOTO_BYTES,
  MAX_VIDEO_BYTES,
  checkMediaFiles,
  exceedsPixelLimit,
  exceedsVideoLength,
  photoMetadataComplete,
} from './reviewPhotos';

const file = (name: string, type: string, size = 1024) => ({ name, type, size });
const none = { images: 0, videos: 0 };

describe('checkMediaFiles (Review.md 8, A4)', () => {
  it('accepts JPEG, PNG and WebP photos and an MP4 video', () => {
    const { accepted, rejected } = checkMediaFiles(
      [file('a.jpg', 'image/jpeg'), file('b.png', 'image/png'), file('c.webp', 'image/webp'), file('d.mp4', 'video/mp4')],
      none,
    );
    expect(accepted.map((a) => [a.file.name, a.kind])).toEqual([
      ['a.jpg', 'image'],
      ['b.png', 'image'],
      ['c.webp', 'image'],
      ['d.mp4', 'video'],
    ]);
    expect(rejected).toEqual([]);
  });

  it('rejects SVG, GIF, other video formats and archives', () => {
    const { accepted, rejected } = checkMediaFiles(
      [file('x.svg', 'image/svg+xml'), file('y.gif', 'image/gif'), file('z.mov', 'video/quicktime'), file('w.zip', 'application/zip')],
      none,
    );
    expect(accepted).toEqual([]);
    expect(rejected.map((r) => r.problem)).toEqual(['TYPE', 'TYPE', 'TYPE', 'TYPE']);
  });

  it('applies 8 MiB to photos and 50 MiB to video', () => {
    const { accepted, rejected } = checkMediaFiles(
      [
        file('ok.jpg', 'image/jpeg', MAX_PHOTO_BYTES),
        file('big.jpg', 'image/jpeg', MAX_PHOTO_BYTES + 1),
        file('ok.mp4', 'video/mp4', MAX_VIDEO_BYTES),
      ],
      none,
    );
    expect(accepted.map((a) => a.file.name)).toEqual(['ok.jpg', 'ok.mp4']);
    expect(rejected).toEqual([{ file: expect.objectContaining({ name: 'big.jpg' }), problem: 'TOO_LARGE' }]);
  });

  it('caps a review at five photos and one video, counting ones already attached', () => {
    const many = Array.from({ length: 4 }, (_, i) => file(`${i}.jpg`, 'image/jpeg'));
    const { accepted, rejected } = checkMediaFiles([...many, file('v.mp4', 'video/mp4')], { images: 2, videos: 1 });
    expect(accepted).toHaveLength(3);
    expect(rejected.map((r) => r.problem)).toEqual(['TOO_MANY', 'TOO_MANY']);
  });
});

describe('limits', () => {
  it('allows 20 megapixels and rejects more', () => {
    expect(exceedsPixelLimit(5000, 4000)).toBe(false);
    expect(exceedsPixelLimit(5001, 4000)).toBe(true);
  });

  it('allows a 60-second video and rejects longer ones', () => {
    expect(exceedsVideoLength(60.4)).toBe(false);
    expect(exceedsVideoLength(61)).toBe(true);
  });
});

describe('media metadata', () => {
  it('needs a description and the ownership declaration', () => {
    expect(photoMetadataComplete({ altText: 'Clouds over Konglak', ownershipDeclared: true })).toBe(true);
    expect(photoMetadataComplete({ altText: '   ', ownershipDeclared: true })).toBe(false);
    expect(photoMetadataComplete({ altText: 'Clouds', ownershipDeclared: false })).toBe(false);
  });
});
