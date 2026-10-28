import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { notificationsQuery, saveNotificationPreferences, updateNotification } from './account';
import { forgetCsrfToken } from './auth';

type Call = [string, RequestInit];
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

let fetchMock: ReturnType<typeof vi.fn>;
const calls = () => fetchMock.mock.calls as unknown as Call[];

beforeEach(() => {
  forgetCsrfToken();
  vi.stubGlobal('document', { documentElement: { lang: 'en' } });
  fetchMock = vi.fn(async (url: string) => (url.endsWith('/csrf') ? json({ csrf_token: 'n.mac' }) : json({ unread: 0 })));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('notification calls (API.md 5.21)', () => {
  it('saves only the editable preference fields', async () => {
    await saveNotificationPreferences({
      standard_email_mode: 'off',
      digest_timezone: 'Asia/Dhaka',
      digest_local_time: '07:30',
      // the page passes the whole object it read, including this read-only field
      ...({ always_immediate: ['critical', 'high'] } as object),
    });
    const put = calls().find(([url]) => url.includes('notification-preferences'))!;
    expect(put[1].method).toBe('PUT');
    expect(JSON.parse(String(put[1].body))).toEqual({ standard_email_mode: 'off', digest_timezone: 'Asia/Dhaka', digest_local_time: '07:30' });
    expect((put[1].headers as Record<string, string>)['X-CSRF-Token']).toBe('n.mac');
  });

  it('marks one item with PATCH and builds the inbox query', async () => {
    await updateNotification('n-1', { archived: true });
    const patch = calls().find(([url]) => url.includes('/notifications/n-1'))!;
    expect(patch[1].method).toBe('PATCH');
    expect(JSON.parse(String(patch[1].body))).toEqual({ archived: true });
    expect(notificationsQuery({ cursor: 'abc', archived: true, limit: 5 })).toBe('/api/v1/notifications?limit=5&cursor=abc&archived=true');
  });
});
