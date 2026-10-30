import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { forgetCsrfToken } from './auth';
import {
  appealRejectedReview,
  editGuestReview,
  editMemberReview,
  getMyReviews,
  getReview,
  myReviewsQuery,
  withdrawMemberReview,
} from './reviews';

type Call = [string, RequestInit];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const RECEIPT = `abr1_${'a'.repeat(43)}`;

let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];
/** The base URL differs between dev and production, so compare the path and query only. */
const pathOf = (url: string) => url.replace(/^https?:\/\/[^/]+/, '');
const lastNonCsrf = (): Call => {
  const [url, init] = calls().filter(([u]) => !u.endsWith('/csrf')).at(-1)!;
  return [pathOf(url), init];
};

beforeEach(() => {
  forgetCsrfToken();
  vi.stubGlobal('document', { documentElement: { lang: 'en' } });
  fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'n.mac' }) : json({ ok: true })));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('GET /reviews/mine query (API.md 5.5a)', () => {
  it('leaves empty values out', () => {
    expect(myReviewsQuery({})).toBe('');
    expect(myReviewsQuery({ status: '', destinationId: '', after: null })).toBe('');
  });
  it('builds status, destination, cursor and limit', () => {
    expect(myReviewsQuery({ status: 'PUBLISHED', destinationId: 'd1', after: 'abc', limit: 20 })).toBe('?status=PUBLISHED&destination_id=d1&after=abc&limit=20');
  });
  it('passes the opaque cursor through untouched', async () => {
    await getMyReviews({ after: 'bTF8MjAyNi0xMC0wMVQwMDowMDowMCswMDowMHw1ZQ', limit: 20 });
    expect(lastNonCsrf()[0]).toContain('after=bTF8MjAyNi0xMC0wMVQwMDowMDowMCswMDowMHw1ZQ');
  });
  it('is a credentialed GET without a CSRF token', async () => {
    await getMyReviews();
    const [, init] = lastNonCsrf();
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('include');
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined();
  });
});

describe('member edit and withdraw (session + CSRF, never a receipt)', () => {
  it('sends the version and only the changed fields with the CSRF token', async () => {
    await editMemberReview('r1', 2, { title: 'New title' });
    const [url, init] = lastNonCsrf();
    expect(url).toBe('/api/v1/reviews/r1/pending');
    expect(init.method).toBe('PATCH');
    expect(init.credentials).toBe('include');
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('n.mac');
    expect(JSON.parse(String(init.body))).toEqual({ expected_version: 2, title: 'New title' });
    expect(String(init.body)).not.toContain('receipt');
  });

  it('can send an empty category set to clear it', async () => {
    await editMemberReview('r1', 3, { category_ratings: {} });
    expect(JSON.parse(String(lastNonCsrf()[1].body))).toEqual({ expected_version: 3, category_ratings: {} });
  });

  it('withdraws with only the version', async () => {
    await withdrawMemberReview('r1', 4);
    const [url, init] = lastNonCsrf();
    expect(url).toBe('/api/v1/reviews/r1/withdraw');
    expect(JSON.parse(String(init.body))).toEqual({ expected_version: 4 });
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('n.mac');
  });

  it('refreshes the CSRF token once and retries when the server refuses it', async () => {
    let first = true;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/csrf')) return json({ csrf_token: first ? 'old' : 'fresh' });
      if (first) {
        first = false;
        return json({ error: { code: 'CSRF_INVALID', message: 'x', request_id: 'r', field_errors: [] } }, 403);
      }
      return json({ review_id: 'r1', status: 'PENDING', version: 3, revision: 2 });
    });
    const result = await editMemberReview('r1', 2, { title: 'T' });
    expect(result.version).toBe(3);
    expect(calls().filter(([url]) => !url.endsWith('/csrf'))).toHaveLength(2);
  });
});

describe('guest edit and appeal (receipt in the body only)', () => {
  it('puts the receipt in the JSON body, sends no cookie and keeps it out of the URL', async () => {
    await editGuestReview('r1', RECEIPT, 1, { body: 'A longer edited note, at least twenty characters.' });
    const [url, init] = lastNonCsrf();
    expect(url).toBe('/api/v1/reviews/r1/pending');
    expect(url).not.toContain('abr1_');
    expect(init.credentials).toBeUndefined();
    expect(JSON.parse(String(init.body))).toMatchObject({ expected_version: 1, receipt_secret: RECEIPT });
    expect(JSON.stringify(init.headers)).not.toContain('abr1_');
    expect(calls().some(([u]) => u.endsWith('/csrf'))).toBe(false); // no session, so no CSRF call
  });

  it('posts the appeal with the review id, receipt and a trimmed statement', async () => {
    await appealRejectedReview('r1', RECEIPT, '  This is my honest account of the trip.  ');
    const [url, init] = lastNonCsrf();
    expect(url).toBe('/api/v1/review-receipts/appeals');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ review_id: 'r1', receipt_secret: RECEIPT, statement: 'This is my honest account of the trip.' });
    expect(url).not.toContain('abr1_');
  });

  it('turns an API error into an ApiError with the code, never echoing the receipt', async () => {
    fetchMock.mockImplementation(async () => json({ error: { code: 'DUPLICATE_APPEAL', message: 'This decision has already been appealed.', request_id: 'q', field_errors: [] } }, 409));
    const error = (await appealRejectedReview('r1', RECEIPT, 'x'.repeat(30)).then(
      () => null,
      (e: unknown) => e,
    )) as { code: string; message: string } | null;
    expect(error?.code).toBe('DUPLICATE_APPEAL');
    expect(error?.message).not.toContain('abr1_');
  });
});

describe('owner view', () => {
  it('encodes the id and is a credentialed GET', async () => {
    await getReview('a/b');
    expect(lastNonCsrf()[0]).toBe('/api/v1/reviews/a%2Fb');
    expect(lastNonCsrf()[1].credentials).toBe('include');
  });
});
