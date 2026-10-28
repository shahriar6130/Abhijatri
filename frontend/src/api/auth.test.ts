import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { forgetCsrfToken, getSession, login, logout, register, reportReview, requestPasswordReset, verifyEmail } from './auth';

type Call = [string, RequestInit];

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const error = (code: string, status: number) => json({ error: { code, message: code, request_id: 'r', field_errors: [] } }, status);

let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];
const headerOf = (call: Call, name: string) => (call[1].headers as Record<string, string>)[name];

beforeEach(() => {
  forgetCsrfToken();
  vi.stubGlobal('document', { documentElement: { lang: 'en' } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('account calls', () => {
  it('send credentials, and never put a secret in the URL', async () => {
    fetchMock = vi.fn(async () => json({ status: 'verification_sent' }, 202));
    vi.stubGlobal('fetch', fetchMock);
    await register({ email: 'a@b.co', password: 'Passw0rdTest99', display_name: 'Nila' });
    await verifyEmail('token-hash-value');
    for (const call of calls()) {
      expect(call[1].credentials).toBe('include');
      expect(call[0]).not.toContain('Passw0rd');
      expect(call[0]).not.toContain('token-hash-value');
    }
    expect(calls()[1][0]).toContain('/api/v1/auth/verify-email');
    expect(JSON.parse(String(calls()[1][1].body))).toEqual({ token_hash: 'token-hash-value' });
  });

  it('asks for the session without a body or a CSRF header', async () => {
    fetchMock = vi.fn(async () => json({ authenticated: false }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await getSession()).toEqual({ authenticated: false });
    expect(calls()[0][1].method).toBe('GET');
    expect(headerOf(calls()[0], 'X-CSRF-Token')).toBeUndefined();
  });

  it('login forgets the CSRF token, because a new session has a new one', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'old.token' }) : url.endsWith('/logout') ? new Response(null, { status: 204 }) : json({ authenticated: true })));
    vi.stubGlobal('fetch', fetchMock);
    await logout();
    await login('a@b.co', 'Passw0rdTest99');
    fetchMock.mockClear();
    await logout();
    expect(calls().map((c) => c[0].replace(/^.*\/api\/v1\/auth/, ''))).toEqual(['/csrf', '/logout']);
  });

  it('a write with a session carries X-CSRF-Token', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'abc.def' }) : new Response(null, { status: 204 })));
    vi.stubGlobal('fetch', fetchMock);
    await logout();
    const write = calls().find((c) => c[0].endsWith('/logout'))!;
    expect(headerOf(write, 'X-CSRF-Token')).toBe('abc.def');
    expect(write[1].method).toBe('POST');
  });

  it('refetches the token and retries once when the server rejects it', async () => {
    let csrfCount = 0;
    let logoutCount = 0;
    fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/csrf')) return json({ csrf_token: `token-${++csrfCount}` });
      return ++logoutCount === 1 ? error('CSRF_INVALID', 403) : new Response(null, { status: 204 });
    });
    vi.stubGlobal('fetch', fetchMock);
    await logout();
    const writes = calls().filter((c) => c[0].endsWith('/logout'));
    expect(writes).toHaveLength(2);
    expect(headerOf(writes[0], 'X-CSRF-Token')).toBe('token-1');
    expect(headerOf(writes[1], 'X-CSRF-Token')).toBe('token-2');
  });

  it('does not retry other errors', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : error('RATE_LIMITED', 429)));
    vi.stubGlobal('fetch', fetchMock);
    await expect(logout()).rejects.toMatchObject({ code: 'RATE_LIMITED' });
    expect(calls().filter((c) => c[0].endsWith('/logout'))).toHaveLength(1);
  });

  it('turns server errors into ApiError with the code', async () => {
    fetchMock = vi.fn(async () => error('INVALID_CREDENTIALS', 401));
    vi.stubGlobal('fetch', fetchMock);
    await expect(login('a@b.co', 'wrongpass1234')).rejects.toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' });
  });

  it('reports a review with the CSRF token, to the reviews route', async () => {
    fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : json({ report_id: 'r', state: 'open' }, 201)));
    vi.stubGlobal('fetch', fetchMock);
    await reportReview('rev-1', 'spam', ' advert ');
    const write = calls().find((c) => c[0].includes('/reports'))!;
    expect(write[0]).toContain('/api/v1/reviews/rev-1/reports');
    expect(write[0]).not.toContain('/auth/');
    expect(headerOf(write, 'X-CSRF-Token')).toBe('a.b');
    expect(JSON.parse(String(write[1].body))).toEqual({ reason_code: 'spam', details: ' advert ' });
  });

  it('password reset request sends only the email and the optional challenge token', async () => {
    fetchMock = vi.fn(async () => json({ status: 'reset_sent' }, 202));
    vi.stubGlobal('fetch', fetchMock);
    await requestPasswordReset('a@b.co');
    expect(JSON.parse(String(calls()[0][1].body))).toEqual({ email: 'a@b.co' });
  });
});
