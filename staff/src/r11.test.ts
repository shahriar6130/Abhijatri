import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  StaffError,
  exportAuditCsv,
  getAuditActions,
  getAuditEvents,
  getDecidedReviews,
  getReasonCodes,
  hidePending,
  reopenReview,
  setCsrfToken,
} from './api';
import { DECISION_GROUP, REASONS, errorText, REOPEN_REASONS, REPORT_REASONS, auditRange, isSuperadmin, reasonsFor, recoveryLeft } from './logic';
import { loadReasonCatalogue, resetReasonCatalogue } from './reasons';
import { toFilters } from './screens/Audit';
import type { ReasonCatalogue } from './types';

type Call = [URL, RequestInit];
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers });
const failure = (code: string, status: number) => json({ error: { code, message: code, request_id: 'r', field_errors: [] } }, status);
let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];
const header = (call: Call, name: string) => (call[1].headers as Record<string, string>)[name];
const withCsrf = (reply: () => Response) => vi.fn(async (url: URL) => (url.pathname.endsWith('/csrf') ? json({ csrf_token: 'a.b' }) : reply()));

beforeEach(() => {
  setCsrfToken(null);
  resetReasonCatalogue();
});
afterEach(() => vi.unstubAllGlobals());

describe('report reasons', () => {
  it('has a label in both languages for all nine reasons, the removal request and the older code', () => {
    const nine = ['spam', 'harassment', 'false_information', 'privacy', 'impersonation', 'safety_misinformation', 'copyright', 'conflict_of_interest', 'other'];
    for (const code of [...nine, 'removal_request', 'offensive']) {
      expect(REPORT_REASONS[code]?.bn.trim(), code).toBeTruthy();
      expect(REPORT_REASONS[code]?.en.trim(), code).toBeTruthy();
    }
    expect(REPORT_REASONS.offensive).toEqual(REPORT_REASONS.harassment);
  });
});

describe('reason catalogue', () => {
  it('maps every review decision to a catalogue group with a built-in fallback', () => {
    for (const decision of Object.keys(REASONS) as (keyof typeof REASONS)[]) {
      expect(DECISION_GROUP[decision]).toBeTruthy();
      expect(REASONS[decision].length).toBeGreaterThan(0);
    }
    expect(DECISION_GROUP.REQUEST_CHANGES).toBe('request_changes');
    expect(REOPEN_REASONS.map((r) => r.code)).toEqual(['rejected-in-error', 'author-corrected']);
  });

  it('prefers the server list when it has arrived and falls back to the built-in one otherwise', () => {
    const served: ReasonCatalogue = { hide: { strict: true, reasons: [{ code: 'from-server', bn: 'সার্ভার', en: 'Server' }] } };
    expect(reasonsFor(served, 'hide', REASONS.HIDE)).toEqual([{ code: 'from-server', bn: 'সার্ভার', en: 'Server' }]);
    expect(reasonsFor(null, 'hide', REASONS.HIDE)).toBe(REASONS.HIDE);
    expect(reasonsFor(served, 'reject', REASONS.REJECT)).toBe(REASONS.REJECT);
    expect(reasonsFor({ hide: { strict: true, reasons: [] } }, 'hide', REASONS.HIDE)).toBe(REASONS.HIDE);
  });

  it('is loaded once, shared, and a failed load is not remembered', async () => {
    fetchMock = vi.fn(async () => json({ groups: { hide: { strict: true, reasons: [{ code: 'x', bn: 'ক', en: 'X' }] } } }));
    vi.stubGlobal('fetch', fetchMock);
    const [a, b] = await Promise.all([loadReasonCatalogue(), loadReasonCatalogue()]);
    expect(a).toBe(b);
    await loadReasonCatalogue();
    expect(calls().filter(([url]) => url.pathname.endsWith('/reason-codes'))).toHaveLength(1);

    resetReasonCatalogue();
    fetchMock = vi.fn(async () => failure('SERVICE_UNAVAILABLE', 503));
    vi.stubGlobal('fetch', fetchMock);
    expect(await loadReasonCatalogue()).toBeNull();
    fetchMock = vi.fn(async () => json({ groups: { hide: { strict: true, reasons: [] } } }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await loadReasonCatalogue()).not.toBeNull();
  });
});

describe('error messages for the new codes', () => {
  it('explains a closed reopen window and a bad cursor in both languages', () => {
    for (const code of ['REOPEN_WINDOW_CLOSED', 'INVALID_CURSOR']) {
      const bn = errorText(new StaffError(409, code), 'bn');
      const en = errorText(new StaffError(409, code), 'en');
      expect(en).not.toMatch(/something went wrong/i);
      expect(bn).not.toBe(en);
    }
  });
});

describe('recovery countdown and roles', () => {
  const now = new Date('2026-11-01T12:00:00Z').getTime();
  it('counts whole days and hours left, and ends at the deadline', () => {
    expect(recoveryLeft('2026-11-30T17:00:00Z', now)).toEqual({ days: 29, hours: 5 });
    expect(recoveryLeft('2026-11-01T12:59:00Z', now)).toEqual({ days: 0, hours: 0 });
    expect(recoveryLeft('2026-11-01T12:00:00Z', now)).toBeNull();
    expect(recoveryLeft('2026-10-01T12:00:00Z', now)).toBeNull();
    expect(recoveryLeft(null, now)).toBeNull();
    expect(recoveryLeft('not a date', now)).toBeNull();
  });
  it('offers reopen and export to a superadmin only', () => {
    expect(isSuperadmin('superadmin')).toBe(true);
    for (const role of ['moderator', null, undefined, '']) expect(isSuperadmin(role)).toBe(false);
  });
});

describe('audit filters', () => {
  it('turns two chosen days into an inclusive start and an exclusive end', () => {
    const range = auditRange('2026-10-05', '2026-10-06');
    expect(new Date(range.from!).getTime()).toBe(new Date('2026-10-05T00:00:00').getTime());
    expect(new Date(range.to!).getTime()).toBe(new Date('2026-10-07T00:00:00').getTime()); // 6 October is included
    expect(auditRange('', '')).toEqual({});
    expect(Object.keys(auditRange('2026-10-05', ''))).toEqual(['from']);
  });

  it('leaves empty fields out and trims the rest', () => {
    const form = { action: ' report.create ', target_type: '', target_id: '', actor_role: 'moderator', request_id: '', fromDay: '', toDay: '' };
    expect(toFilters(form)).toEqual({ action: 'report.create', actor_role: 'moderator' });
  });

  it('sends every filter and the cursor, and nothing that is empty', async () => {
    fetchMock = vi.fn(async () => json({ items: [], next_cursor: 'c2', next_before: null }));
    vi.stubGlobal('fetch', fetchMock);
    const page = await getAuditEvents({ action: 'report.create', actor_role: 'moderator', request_id: 'req-1', from: '2026-10-05T00:00:00Z', to: '2026-10-06T00:00:00Z', target_type: '' }, 'abc');
    expect(page.next_cursor).toBe('c2');
    const url = calls()[0][0];
    expect(url.pathname).toBe('/api/v1/admin/audit-events');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      action: 'report.create', actor_role: 'moderator', request_id: 'req-1', from: '2026-10-05T00:00:00Z', to: '2026-10-06T00:00:00Z', cursor: 'abc', limit: '50',
    });
  });

  it('loads the action list and the reason catalogue with plain reads', async () => {
    fetchMock = vi.fn(async (url: URL) => json(url.pathname.endsWith('/actions') ? { actions: ['a.b'], denied_prefix: 'denied.' } : { groups: {} }));
    vi.stubGlobal('fetch', fetchMock);
    expect((await getAuditActions()).actions).toEqual(['a.b']);
    expect(await getReasonCodes()).toEqual({ groups: {} });
    expect(calls().every((call) => call[1].method === undefined || call[1].method === 'GET')).toBe(true);
  });
});

describe('audit export', () => {
  it('returns the csv with the row count and whether it was cut off', async () => {
    fetchMock = vi.fn(async () => new Response('id,action\n1,report.create\n', { status: 200, headers: { 'X-Row-Count': '1', 'X-Truncated': 'true' } }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await exportAuditCsv({ action: 'report.create', request_id: '' });
    expect(result).toEqual({ csv: 'id,action\n1,report.create\n', rows: 1, truncated: true });
    const [url, init] = calls()[0];
    expect(url.pathname).toBe('/api/v1/admin/audit-events/export');
    expect(url.searchParams.get('action')).toBe('report.create');
    expect(url.searchParams.has('request_id')).toBe(false);
    expect(init.credentials).toBe('include');
  });

  it('turns a refusal into a StaffError with the server code', async () => {
    fetchMock = vi.fn(async () => failure('FORBIDDEN', 403));
    vi.stubGlobal('fetch', fetchMock);
    await expect(exportAuditCsv({})).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' });
    fetchMock = vi.fn(async () => {
      throw new TypeError('offline');
    });
    vi.stubGlobal('fetch', fetchMock);
    await expect(exportAuditCsv({})).rejects.toBeInstanceOf(StaffError);
  });
});

describe('hide pending a decision, the lists and reopen', () => {
  it('sends the report version, the lease and the keep-rating choice exactly as given', async () => {
    fetchMock = withCsrf(() => json({ report_id: 'r', state: 'in_review', version: 3, case_id: 'c', review_status: 'HIDDEN', counted_rating: null }));
    vi.stubGlobal('fetch', fetchMock);
    await hidePending('rep-1', { expectedVersion: 2, reasonCode: 'privacy-pending', countsTowardRating: false, taskId: 't', leaseToken: 'l' });
    const write = calls().find(([url]) => url.pathname.endsWith('/hide-pending'))!;
    expect(write[0].pathname).toBe('/api/v1/admin/reports/rep-1/hide-pending');
    expect(write[1].method).toBe('POST');
    expect(header(write, 'X-CSRF-Token')).toBe('a.b');
    expect(JSON.parse(String(write[1].body))).toEqual({ expected_version: 2, reason_code: 'privacy-pending', counts_toward_rating: false, task_id: 't', lease_token: 'l' });
    await hidePending('rep-1', { expectedVersion: 2, reasonCode: 'privacy-pending', countsTowardRating: true, taskId: 't', leaseToken: 'l' });
    expect(JSON.parse(String(calls().filter(([url]) => url.pathname.endsWith('/hide-pending'))[1][1].body)).counts_toward_rating).toBe(true);
  });

  it('lists rejected or hidden reviews with the cursor', async () => {
    fetchMock = vi.fn(async () => json({ items: [], next_cursor: null }));
    vi.stubGlobal('fetch', fetchMock);
    await getDecidedReviews('REJECTED', 'cur');
    await getDecidedReviews('HIDDEN');
    expect(Object.fromEntries(calls()[0][0].searchParams)).toEqual({ status: 'REJECTED', after: 'cur', limit: '50' });
    expect(Object.fromEntries(calls()[1][0].searchParams)).toEqual({ status: 'HIDDEN', limit: '50' });
  });

  it('reopens with the version and reason and drops an empty note', async () => {
    fetchMock = withCsrf(() => json({ review_id: 'r', status: 'PENDING', version: 4 }));
    vi.stubGlobal('fetch', fetchMock);
    await reopenReview('rev-9', { expectedVersion: 3, reasonCode: 'rejected-in-error', note: '' });
    const write = calls().find(([url]) => url.pathname.endsWith('/reopen'))!;
    expect(write[0].pathname).toBe('/api/v1/admin/reviews/rev-9/reopen');
    expect(JSON.parse(String(write[1].body))).toEqual({ expected_version: 3, reason_code: 'rejected-in-error' });
  });

  it('surfaces the server code when the window has closed', async () => {
    fetchMock = withCsrf(() => failure('REOPEN_WINDOW_CLOSED', 409));
    vi.stubGlobal('fetch', fetchMock);
    await expect(reopenReview('rev-9', { expectedVersion: 3, reasonCode: 'rejected-in-error' })).rejects.toMatchObject({ code: 'REOPEN_WINDOW_CLOSED', status: 409 });
  });
});
