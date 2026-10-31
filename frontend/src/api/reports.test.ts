import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { forgetCsrfToken } from './auth';
import { ApiError, NETWORK_ERROR } from './client';
import {
  CONTACT_MAX,
  REPORT_REASONS,
  contactProblem,
  getMyReports,
  isReviewId,
  reportFailure,
  reportReview,
  reportReviewAnonymously,
  requestRemoval,
} from './reports';

type Call = [string, RequestInit];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const error = (code: string, status: number) => json({ error: { code, message: code, request_id: 'r', field_errors: [] } }, status);
let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];
const headerOf = (call: Call, name: string) => (call[1].headers as Record<string, string> | undefined)?.[name];

beforeEach(() => {
  forgetCsrfToken();
  vi.stubGlobal('document', { documentElement: { lang: 'en' } });
});
afterEach(() => vi.unstubAllGlobals());

describe('report reasons', () => {
  it('lists the nine reasons of Review.md 5.4 with both languages and no removal code', () => {
    expect(REPORT_REASONS.map((r) => r.value)).toEqual([
      'spam', 'harassment', 'false_information', 'privacy', 'impersonation', 'safety_misinformation', 'copyright', 'conflict_of_interest', 'other',
    ]);
    for (const reason of REPORT_REASONS) {
      expect(reason.bn.trim(), reason.value).toBeTruthy();
      expect(reason.en.trim(), reason.value).toBeTruthy();
      expect(reason.bn).not.toBe(reason.en);
    }
    expect(REPORT_REASONS.some((r) => (r.value as string) === 'removal_request')).toBe(false);
  });
});

describe('member report', () => {
  it('uses the session and the CSRF token and sends the details as typed', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : json({ report_id: 'r', state: 'open' }, 201)));
    vi.stubGlobal('fetch', fetchMock);
    await reportReview('rev 1', 'privacy', 'shows my phone');
    const write = calls().find((c) => c[0].includes('/reports'))!;
    expect(write[0]).toContain('/api/v1/reviews/rev%201/reports');
    expect(headerOf(write, 'X-CSRF-Token')).toBe('a.b');
    expect(write[1].credentials).toBe('include');
    expect(JSON.parse(String(write[1].body))).toEqual({ reason_code: 'privacy', details: 'shows my phone' });
  });
});

describe('anonymous report', () => {
  it('sends no cookie and no CSRF token, only the challenge token, and trims what was typed', async () => {
    fetchMock = vi.fn(async () => json({ received: true }, 202));
    vi.stubGlobal('fetch', fetchMock);
    const answer = await reportReviewAnonymously({ reviewId: ' 3f2a1c0e-1111-4222-8333-444455556666 ', reasonCode: 'copyright', details: '  mine  ', contact: ' a@b.co ', turnstileToken: 'tok' });
    expect(answer).toEqual({ received: true });
    const [url, init] = calls()[0];
    expect(url).toContain('/api/v1/public/review-reports');
    expect(init.credentials).not.toBe('include');
    expect(headerOf(calls()[0], 'X-CSRF-Token')).toBeUndefined();
    expect(JSON.parse(String(init.body))).toEqual({
      review_id: '3f2a1c0e-1111-4222-8333-444455556666', reason_code: 'copyright', details: 'mine', contact: 'a@b.co', turnstile_token: 'tok',
    });
    expect(calls().filter((c) => c[0].includes('/auth/csrf'))).toHaveLength(0);
  });

  it('leaves out an empty contact, empty details and a missing token', async () => {
    fetchMock = vi.fn(async () => json({ received: true }, 202));
    vi.stubGlobal('fetch', fetchMock);
    await reportReviewAnonymously({ reviewId: '3f2a1c0e-1111-4222-8333-444455556666', reasonCode: 'spam', details: '  ', contact: '' });
    expect(JSON.parse(String(calls()[0][1].body))).toEqual({ review_id: '3f2a1c0e-1111-4222-8333-444455556666', reason_code: 'spam' });
  });
});

describe('removal request', () => {
  it('sends the review, the statement, the required contact and the challenge token', async () => {
    fetchMock = vi.fn(async () => json({ received: true }, 202));
    vi.stubGlobal('fetch', fetchMock);
    await requestRemoval({ reviewId: '3f2a1c0e-1111-4222-8333-444455556666', statement: '  I wrote it in March  ', contact: ' +880 1712-345678 ', turnstileToken: 't' });
    const [url, init] = calls()[0];
    expect(url).toContain('/api/v1/public/removal-requests');
    expect(JSON.parse(String(init.body))).toEqual({ review_id: '3f2a1c0e-1111-4222-8333-444455556666', statement: 'I wrote it in March', contact: '+880 1712-345678', turnstile_token: 't' });
  });
});

describe('my reports', () => {
  it('reads the list with the cursor and the session', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : json({ items: [], next_cursor: null })));
    vi.stubGlobal('fetch', fetchMock);
    await getMyReports('cur+1');
    const read = calls().find((c) => c[0].includes('/reports/mine'))!;
    expect(read[0]).toContain('/api/v1/reports/mine?cursor=cur%2B1');
    expect(read[1].credentials).toBe('include');
  });
});

describe('what went wrong', () => {
  const fail = (code: string, status = 400) => new ApiError(status, code, 'm', 'r', []);
  it('maps the server codes to a kind the screens turn into a sentence', () => {
    expect(reportFailure(fail('DUPLICATE_OPEN_REPORT', 409))).toBe('duplicate');
    expect(reportFailure(fail('RATE_LIMITED', 429))).toBe('rate_limited');
    expect(reportFailure(fail('ACCOUNT_RESTRICTED', 403))).toBe('restricted');
    expect(reportFailure(fail('ACCOUNT_DISABLED', 403))).toBe('restricted');
    expect(reportFailure(fail('CHALLENGE_FAILED', 403))).toBe('challenge');
    expect(reportFailure(fail('FORBIDDEN', 403))).toBe('not_allowed');
    expect(reportFailure(fail('VALIDATION_FAILED', 422))).toBe('invalid');
    expect(reportFailure(fail(NETWORK_ERROR, 0))).toBe('offline');
    expect(reportFailure(fail('SOMETHING_ELSE', 500))).toBe('other');
    expect(reportFailure(new Error('x'))).toBe('other');
    expect(reportFailure(undefined)).toBe('other');
  });

  it('turns a real refusal from the API into the matching kind', async () => {
    fetchMock = vi.fn(async () => error('RATE_LIMITED', 429));
    vi.stubGlobal('fetch', fetchMock);
    const failure = await reportReviewAnonymously({ reviewId: '3f2a1c0e-1111-4222-8333-444455556666', reasonCode: 'spam' }).catch((e) => e);
    expect(reportFailure(failure)).toBe('rate_limited');
  });
});

describe('contact and review id checks', () => {
  it('accepts an email address or a phone number and nothing else', () => {
    for (const ok of ['a@b.co', 'nila.rahman@example.com', '+880 1712-345678', '01712345678', '(02) 5555-0101']) expect(contactProblem(ok, true), ok).toBeNull();
    for (const bad of ['not a contact', 'a@b', '12', 'a b@c.com', '@@', 'abc123']) expect(contactProblem(bad, true), bad).toBe('INVALID');
  });
  it('treats an empty contact as fine when optional and as missing when required', () => {
    expect(contactProblem('', false)).toBeNull();
    expect(contactProblem('   ', false)).toBeNull();
    expect(contactProblem('', true)).toBe('REQUIRED');
    expect(contactProblem('x'.repeat(CONTACT_MAX + 1), false)).toBe('TOO_LONG');
  });
  it('recognises a review id as a person pastes it', () => {
    expect(isReviewId('3f2a1c0e-1111-4222-8333-444455556666')).toBe(true);
    expect(isReviewId('  3F2A1C0E-1111-4222-8333-444455556666  ')).toBe(true);
    for (const bad of ['', 'abc', '3f2a1c0e-1111-4222-8333', '3f2a1c0e11114222833344445555666 6', '../../etc/passwd']) expect(isReviewId(bad), bad).toBe(false);
  });
});
