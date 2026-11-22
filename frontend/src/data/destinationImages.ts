/**
 * Licensed destination photographs (Platform Foundation 17; Decisions 2026-11-04).
 *
 * Each image is a Wikimedia Commons photograph under a Creative Commons licence, resized to 1024 px
 * (plus a 480 px variant) and re-encoded as WebP (which also removes EXIF and GPS metadata), and self-hosted under
 * /images/destinations so the site never hotlinks. CC BY-SA requires the author, the licence with a
 * link, the source and a note of the change; `ImageCredit` renders all four, and
 * Docs/Image-Credits.md lists them. Never add an image here without its licence record.
 *
 * Destinations are matched by English name because record ids differ between databases.
 */

export interface DestinationImage {
  src: string;
  /** 480 px variant (about a fifth of the bytes) for closed panels and low-data connections. */
  srcSmall: string;
  width: number;
  height: number;
  alt: { bn: string; en: string };
  /** The place's name, for when the destination list has not loaded (front page hero). */
  place: { bn: string; en: string };
  credit: {
    author: string;
    licence: string;
    licenceUrl: string;
    source: string;
  };
}

const IMAGES: Record<string, DestinationImage> = {
  "Cox's Bazar": {
    place: { bn: 'কক্সবাজার', en: 'Cox\'s Bazar' },
    src: '/images/destinations/coxs-bazar.webp',
    srcSmall: '/images/destinations/coxs-bazar-480.webp',
    width: 1024,
    height: 682,
    alt: {
      bn: 'সূর্যাস্তের সময় কক্সবাজার সৈকতে ভেজা বালুতে হেঁটে চলা মানুষের ছায়া',
      en: "People walking on the wet sand of Cox's Bazar beach at sunset",
    },
    credit: {
      author: 'Tanweer Morshed',
      licence: 'CC BY-SA 3.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/3.0/',
      source: 'https://commons.wikimedia.org/wiki/File:Cox%27s_Bazar_sea_beach_01.jpg',
    },
  },
  'Sajek Valley': {
    place: { bn: 'সাজেক ভ্যালি', en: 'Sajek Valley' },
    src: '/images/destinations/sajek-valley.webp',
    srcSmall: '/images/destinations/sajek-valley-480.webp',
    width: 1024,
    height: 683,
    alt: {
      bn: 'সাজেক ভ্যালিতে সবুজ পাহাড়ের ঢালে জমে থাকা মেঘ',
      en: 'Clouds settling between green hills at Sajek Valley',
    },
    credit: {
      author: 'Sahriar ahmed tasvir',
      licence: 'CC BY-SA 4.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
      source: 'https://commons.wikimedia.org/wiki/File:Clouds_at_Sajek_Valley_20171220.jpg',
    },
  },
  Sylhet: {
    place: { bn: 'সিলেট', en: 'Sylhet' },
    src: '/images/destinations/sylhet.webp',
    srcSmall: '/images/destinations/sylhet-480.webp',
    width: 1024,
    height: 682,
    alt: {
      bn: 'রাতারগুল জলাবনে ডুবে থাকা গাছের মাঝ দিয়ে নৌকায় যাত্রী',
      en: 'A boat passing between flooded trees in Ratargul Swamp Forest, Sylhet',
    },
    credit: {
      author: 'Sumon Mallick',
      licence: 'CC BY-SA 4.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
      source: 'https://commons.wikimedia.org/wiki/File:Ratargul_Swamp_Forest,_Sylhet..jpg',
    },
  },
  Sundarbans: {
    place: { bn: 'সুন্দরবন', en: 'Sundarbans' },
    src: '/images/destinations/sundarbans.webp',
    srcSmall: '/images/destinations/sundarbans-480.webp',
    width: 1024,
    height: 682,
    alt: {
      bn: 'করমজলে সুন্দরবনের নদীর পাড়ে ঘন ম্যানগ্রোভ বন',
      en: 'Dense mangrove forest along a river at Karamjal in the Sundarbans',
    },
    credit: {
      author: 'Shahid BDWiki',
      licence: 'CC BY-SA 4.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
      source: 'https://commons.wikimedia.org/wiki/File:Karamjal_Point,_SUNDARBAN.jpg',
    },
  },
  Bandarban: {
    place: { bn: 'বান্দরবান', en: 'Bandarban' },
    src: '/images/destinations/bandarban.webp',
    srcSmall: '/images/destinations/bandarban-480.webp',
    width: 1024,
    height: 576,
    alt: {
      bn: 'নীলগিরি থেকে দেখা বান্দরবানের পাহাড়শ্রেণি',
      en: 'Hill ranges of Bandarban seen from Nilgiri',
    },
    credit: {
      author: 'Tanvir Rahat',
      licence: 'CC BY-SA 4.0',
      licenceUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
      source: 'https://commons.wikimedia.org/wiki/File:Nilgiri,_Bandarban,_Bangladesh.jpg',
    },
  },
};

export function destinationImage(nameEn: string): DestinationImage | undefined {
  return IMAGES[nameEn];
}

/** Every licensed photo with its destination's English name, in a fixed order (front page hero and credits). */
export function allDestinationImages(): [string, DestinationImage][] {
  return Object.entries(IMAGES);
}
