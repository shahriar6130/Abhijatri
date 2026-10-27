import { describe, expect, it } from 'vitest';
import {
  REVIEW_CATEGORIES,
  buildGuestReviewPayload,
  cleanCategoryRatings,
  detectReviewLanguage,
  generateReceipt,
  isReceiptFormat,
  type GuestReviewDraft,
} from './reviews';

const draft = (overrides: Partial<GuestReviewDraft> = {}): GuestReviewDraft => ({
  destinationId: 'ea432771-6cdb-542b-88f7-48815c949a43',
  clientDraftId: '0b9b2b1e-7a43-4c2e-8b57-0e0d8f6d6a11',
  receipt: generateReceipt(),
  guestScopeSecret: 'x'.repeat(64),
  displayName: '  সাদিয়া রহমান  ',
  language: 'BN',
  travellerType: 'STUDENT',
  comfortTier: 'ECONOMY',
  visitMonth: '2026-09',
  title: '  Clouds below the helipad ',
  note: '  The escort left late, but the sunrise was worth it. ',
  overallRating: 4,
  categoryRatings: {},
  ...overrides,
});

describe('receipt (PF 13.2)', () => {
  it('is abr1_ plus 43 base64url characters', () => {
    for (let i = 0; i < 50; i += 1) {
      const receipt = generateReceipt();
      expect(receipt).toMatch(/^abr1_[A-Za-z0-9_-]{43}$/);
      expect(isReceiptFormat(receipt)).toBe(true);
    }
  });

  it('is different every time', () => {
    const receipts = new Set(Array.from({ length: 200 }, generateReceipt));
    expect(receipts.size).toBe(200);
  });

  it('rejects malformed values', () => {
    expect(isReceiptFormat('abr1_short')).toBe(false);
    expect(isReceiptFormat(`abr2_${'a'.repeat(43)}`)).toBe(false);
    expect(isReceiptFormat(`abr1_${'a'.repeat(42)}+`)).toBe(false);
  });
});

describe('category ratings (Review.md 3.1)', () => {
  it('lists the seven frozen categories once', () => {
    expect(REVIEW_CATEGORIES).toEqual([
      'CLEANLINESS',
      'ACCESSIBILITY',
      'HOSPITALITY',
      'FOOD',
      'TRANSPORT',
      'SAFETY_PERCEPTION',
      'VALUE',
    ]);
  });

  it('keeps only integer ratings from 1 to 5', () => {
    expect(cleanCategoryRatings({ CLEANLINESS: 5, FOOD: 0, VALUE: 6, TRANSPORT: 2.5, HOSPITALITY: 1 })).toEqual({
      CLEANLINESS: 5,
      HOSPITALITY: 1,
    });
  });
});

describe('buildGuestReviewPayload (API.md 5.2)', () => {
  it('maps the form to the contract, trimming text and normalising the name to NFC', () => {
    const decomposed = 'Café';
    const payload = buildGuestReviewPayload(draft({ displayName: ` ${decomposed} ` }), { sendCategoryRatings: false });
    expect(payload).toMatchObject({
      destination_id: 'ea432771-6cdb-542b-88f7-48815c949a43',
      client_draft_id: '0b9b2b1e-7a43-4c2e-8b57-0e0d8f6d6a11',
      guest_display_name: 'Café'.normalize('NFC'),
      visit_month: '2026-09-01',
      title: 'Clouds below the helipad',
      body: 'The escort left late, but the sunrise was worth it.',
      overall_rating: 4,
      consent_version: '2026-10-01',
    });
    expect(payload.receipt_secret).toMatch(/^abr1_/);
  });

  it('never sends a guest tag: the server derives it from the scope secret', () => {
    const payload = buildGuestReviewPayload(draft(), { sendCategoryRatings: false });
    expect(payload).not.toHaveProperty('guest_tag');
    expect(payload).toHaveProperty('guest_scope_secret');
  });

  it('never sends unknown fields while the API does not accept category ratings', () => {
    const payload = buildGuestReviewPayload(draft({ categoryRatings: { FOOD: 4 } }), { sendCategoryRatings: false });
    expect(payload).not.toHaveProperty('category_ratings');
    expect(Object.keys(payload).sort()).toEqual(
      [
        'body',
        'client_draft_id',
        'comfort_tier',
        'consent_version',
        'destination_id',
        'guest_display_name',
        'guest_scope_secret',
        'language',
        'overall_rating',
        'receipt_secret',
        'title',
        'traveller_type',
        'visit_month',
      ].sort(),
    );
  });

  it('sends only the rated categories once enabled', () => {
    const payload = buildGuestReviewPayload(draft({ categoryRatings: { FOOD: 4, SAFETY_PERCEPTION: 5 } }), {
      sendCategoryRatings: true,
    });
    expect(payload.category_ratings).toEqual({ FOOD: 4, SAFETY_PERCEPTION: 5 });
  });

  it('omits category_ratings when nothing was rated, even when enabled', () => {
    const payload = buildGuestReviewPayload(draft(), { sendCategoryRatings: true });
    expect(payload).not.toHaveProperty('category_ratings');
  });
});

describe('review language follows the text, not the interface (Gantt R09)', () => {
  it('labels Bangla script as BN', () => {
    expect(detectReviewLanguage('মেঘের রাজ্যে দুই দিন। কংলাক পাড়ার সূর্যোদয় অসাধারণ।')).toBe('BN');
  });

  it('labels English as EN', () => {
    expect(detectReviewLanguage('Clouds below the helipad. The sunrise was worth it.')).toBe('EN');
  });

  it('labels a real mix as MIXED', () => {
    expect(detectReviewLanguage('Sajek trip ছিল অসাধারণ, but the road was rough পাহাড়ি পথে')).toBe('MIXED');
  });

  it('ignores a few borrowed words and numbers', () => {
    expect(detectReviewLanguage('বাঘাইহাট থেকে এসকর্ট 10:30-এ ছেড়েছিল, CNG ভাড়া বেশি চেয়েছিল, তবু সব মিলিয়ে ভালো')).toBe('BN');
  });

  it('returns null before any letters are typed', () => {
    expect(detectReviewLanguage('   12345 !!! ')).toBeNull();
  });
});

describe('the note is sent exactly as written', () => {
  it('keeps a Bangla note in Bangla and an English note in English', () => {
    const bangla = 'বাঘাইহাট থেকে এসকর্ট সকাল সাড়ে দশটায় ছেড়েছিল।';
    const english = 'The escort left Baghaihat at half past ten.';
    expect(buildGuestReviewPayload(draft({ note: bangla, language: 'BN' }), { sendCategoryRatings: false }).body).toBe(bangla);
    expect(buildGuestReviewPayload(draft({ note: english, language: 'EN' }), { sendCategoryRatings: false }).body).toBe(english);
  });
});
