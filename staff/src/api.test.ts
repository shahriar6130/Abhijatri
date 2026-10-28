import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StaffError, assignTask, claimTask, decide, getDeliveries, getQueue, login, markInboxRead, removeSuppression, retryDelivery, setCsrfToken, transitionReport } from './api';

type Call = [URL, RequestInit];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const failure = (code: string, status: number) => json({ error: { code, message: code, request_id: 'r', field_errors: [] } }, status);

let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];
const header = (call: Call, name: string) => (call[1].headers as Record<string, string>)[name];

beforeEach(() => setCsrfToken(null));
afterEach(() => vi.unstubAllGlobals());

describe('staff API client', () => {
  it('sends the session cookie, never caches, and keeps secrets out of the URL', async () => {
    fetchMock = vi.fn(async () => json({ items: [], generated_at: '' }));
    vi.stubGlobal('fetch', fetchMock);
    await getQueue('report');
    const [url, init] = calls()[0];
    expect(init.credentials).toBe('include');
    expect(init.cache).toBe('no-store');
    expect(url.pathname).toBe('/api/v1/admin/queue');
    expect(url.searchParams.get('task_type')).toBe('report');
    expect(header(calls()[0], 'X-CSRF-Token')).toBeUndefined();
  });

  it('a write fetches the CSRF token once and reuses it', async () => {
    fetchMock = vi.fn(async (url: URL) => (url.pathname.endsWith('/csrf') ? json({ csrf_token: 'n.mac' }) : json({ id: 't' })));
    vi.stubGlobal('fetch', fetchMock);
    await claimTask('task-1');
    await claimTask('task-2');
    expect(calls().filter(([url]) => url.pathname.endsWith('/csrf'))).toHaveLength(1);
    const writes = calls().filter(([url]) => url.pathname.includes('/tasks/'));
    expect(writes.map((call) => header(call, 'X-CSRF-Token'))).toEqual(['n.mac', 'n.mac']);
    expect(writes[0][1].method).toBe('POST');
  });

  it('refetches the token and retries once when the server rejects it', async () => {
    let csrfCount = 0;
    let claims = 0;
    fetchMock = vi.fn(async (url: URL) => {
      if (url.pathname.endsWith('/csrf')) return json({ csrf_token: `t${++csrfCount}` });
      return ++claims === 1 ? failure('CSRF_INVALID', 403) : json({ id: 'x' });
    });
    vi.stubGlobal('fetch', fetchMock);
    await claimTask('task-1');
    const writes = calls().filter(([url]) => url.pathname.includes('/tasks/'));
    expect(writes.map((call) => header(call, 'X-CSRF-Token'))).toEqual(['t1', 't2']);
  });

  it('sends decisions with an Idempotency-Key and the lease', async () => {
    fetchMock = vi.fn(async (url: URL) => (url.pathname.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : json({ review_id: 'r', status: 'PUBLISHED', version: 2 })));
    vi.stubGlobal('fetch', fetchMock);
    await decide('review-1', { taskId: 't', leaseToken: 'l', expectedVersion: 3, decision: 'PUBLISH', reasonCode: 'meets-policy' }, 'ui-key-0001');
    const write = calls().find(([url]) => url.pathname.includes('moderation-actions'))!;
    expect(header(write, 'Idempotency-Key')).toBe('ui-key-0001');
    expect(JSON.parse(String(write[1].body))).toEqual({ task_id: 't', lease_token: 'l', expected_version: 3, decision: 'PUBLISH', reason_code: 'meets-policy' });
  });

  it('report transitions carry the lease and the version', async () => {
    fetchMock = vi.fn(async (url: URL) => (url.pathname.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : json({ report_id: 'r', state: 'in_review', version: 2 })));
    vi.stubGlobal('fetch', fetchMock);
    await transitionReport('rep-1', { taskId: 't', leaseToken: 'l', expectedVersion: 1, to: 'in_review', reasonCode: 'looking' });
    const write = calls().find(([url]) => url.pathname.includes('/reports/rep-1/transition'))!;
    expect(JSON.parse(String(write[1].body))).toMatchObject({ to: 'in_review', expected_version: 1, task_id: 't', lease_token: 'l' });
  });

  it('sign-in is made without a CSRF token, because no session exists yet', async () => {
    fetchMock = vi.fn(async () => json({ authenticated: false }));
    vi.stubGlobal('fetch', fetchMock);
    await login('a@b.co', 'Passw0rdTest99');
    expect(calls()).toHaveLength(1);
    expect(calls()[0][0].pathname).toBe('/api/v1/auth/login');
    expect(header(calls()[0], 'X-CSRF-Token')).toBeUndefined();
  });

  it('turns API errors into StaffError with the code and field errors', async () => {
    fetchMock = vi.fn(async () => json({ error: { code: 'VALIDATION_FAILED', field_errors: [{ field: 'password', code: 'WEAK' }] } }, 422));
    vi.stubGlobal('fetch', fetchMock);
    await expect(login('a@b.co', 'x')).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED', fieldErrors: [{ field: 'password', code: 'WEAK' }] });
  });

  it('reports an unreachable API as NETWORK_ERROR', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(getQueue()).rejects.toBeInstanceOf(StaffError);
    await expect(getQueue()).rejects.toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
  });

  it('notification operations use the right method, carry the CSRF token and never put addresses in the URL', async () => {
    fetchMock = vi.fn(async (url: URL) => (url.pathname.endsWith('/csrf') ? json({ csrf_token: 'c.t' }) : json({ items: [], counts: {} })));
    vi.stubGlobal('fetch', fetchMock);
    await getDeliveries('ambiguous');
    await retryDelivery('d-1', 'checked the provider');
    await removeSuppression('s-1', 'asked to receive mail again');
    await markInboxRead('n-1');
    await assignTask('task-1', null);
    const byPath = (part: string) => calls().find(([url]) => url.pathname.includes(part))!;
    expect(byPath('notification-deliveries')[0].searchParams.get('status')).toBe('ambiguous');
    expect(byPath('/retry')[1].method).toBe('POST');
    expect(JSON.parse(String(byPath('/retry')[1].body))).toEqual({ reason: 'checked the provider' });
    expect(byPath('notification-suppressions/s-1')[1].method).toBe('DELETE');
    expect(header(byPath('notification-suppressions/s-1'), 'X-CSRF-Token')).toBe('c.t');
    expect(byPath('/notifications/n-1')[1].method).toBe('PATCH');
    expect(JSON.parse(String(byPath('/notifications/n-1')[1].body))).toEqual({ read: true });
    expect(JSON.parse(String(byPath('/assign')[1].body))).toEqual({ user_id: null });
  });
});
