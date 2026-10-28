import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  GUEST_NAME_MAX,
  guestTag,
  loadGuestName,
  loadGuestTag,
  normalizeGuestName,
  recordDailyVisit,
  saveGuestName,
  signOutGuest,
  startAsNewGuest,
} from './guests';

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => void values.delete(key),
    setItem: (key, value) => void values.set(key, String(value)),
  };
}

const blockedStorage = {
  getItem: () => {
    throw new Error('blocked');
  },
  setItem: () => {
    throw new Error('blocked');
  },
  removeItem: () => {
    throw new Error('blocked');
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('guestTag', () => {
  it('matches the spec test vector (parity with backend/app/guest_tag.py)', async () => {
    const secret = 'Zm9vYmFyLXRlc3QtdmVjdG9yLW5vdC1hLXJlYWwtc2VjcmV0LTAwMDAwMDAwMDAw';
    expect(await guestTag(secret)).toBe('1C669-J0TDY');
  });

  it('is stable per browser and changes only on "start as a new guest"', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    const first = await loadGuestTag();
    expect(first).toMatch(/^[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}$/);
    expect(await loadGuestTag()).toBe(first);
    const renewed = await startAsNewGuest();
    expect(renewed).not.toBe(first);
    expect(await loadGuestTag()).toBe(renewed);
  });

  it('keeps one tag for the tab when storage is blocked', async () => {
    vi.stubGlobal('localStorage', blockedStorage);
    expect(await loadGuestTag()).toBe(await loadGuestTag());
  });
});

describe('normalizeGuestName', () => {
  it('trims and NFC-normalises', () => {
    const decomposed = 'সাদিয়া'.normalize('NFD');
    expect(normalizeGuestName(`  ${decomposed}  `)).toBe('সাদিয়া'.normalize('NFC'));
  });

  it('returns null for blank input', () => {
    expect(normalizeGuestName('   ')).toBeNull();
  });

  it('caps the name at 80 code points, counting Bangla correctly', () => {
    const long = 'ক'.repeat(GUEST_NAME_MAX + 10);
    expect([...(normalizeGuestName(long) ?? '')]).toHaveLength(GUEST_NAME_MAX);
  });
});

describe('guest name session', () => {
  const day1 = new Date('2026-10-20T10:00:00Z');

  it('round-trips through localStorage and can be cleared', () => {
    vi.stubGlobal('localStorage', memoryStorage());
    saveGuestName('Sadia', day1);
    expect(loadGuestName(day1)).toBe('Sadia');
    saveGuestName(null);
    expect(loadGuestName(day1)).toBeNull();
  });

  it('is remembered for 30 days and forgotten after', () => {
    vi.stubGlobal('localStorage', memoryStorage());
    saveGuestName('Sadia', day1);
    expect(loadGuestName(new Date('2026-11-19T10:00:00Z'))).toBe('Sadia'); // day 30
    expect(loadGuestName(new Date('2026-11-20T10:00:00Z'))).toBeNull(); // day 31
  });

  it('a visit renews the 30 days', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    vi.stubGlobal('document', { documentElement: { lang: 'en' } });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })));
    saveGuestName('Sadia', day1);
    await recordDailyVisit(new Date('2026-11-10T10:00:00Z'));
    expect(loadGuestName(new Date('2026-12-05T10:00:00Z'))).toBe('Sadia');
  });

  it('tolerates blocked storage', () => {
    vi.stubGlobal('localStorage', blockedStorage);
    expect(() => saveGuestName('Sadia')).not.toThrow();
    expect(loadGuestName()).toBeNull();
  });
});

describe('recordDailyVisit', () => {
  // 10:00 UTC is 16:00 in Dhaka on the same date; the next call is a Dhaka day later.
  const day1 = new Date('2026-10-20T10:00:00Z');
  const day2 = new Date('2026-10-21T10:00:00Z');
  let fetchMock: ReturnType<typeof vi.fn>;

  const bodies = () =>
    fetchMock.mock.calls.map((call) => JSON.parse(String((call as unknown as [string, RequestInit])[1].body)));

  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: { lang: 'en' } });
    fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends exactly { first_visit }: never the name, tag or secret', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    saveGuestName('Sadia');
    await recordDailyVisit(day1);
    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/v1/guest-visits');
    expect(bodies()).toEqual([{ first_visit: true }]);
  });

  it('counts a browser once per Dhaka day and is new only on its first day', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    expect(await recordDailyVisit(day1)).toBe(true);
    expect(await recordDailyVisit(day1)).toBe(false); // same day: no request
    expect(await recordDailyVisit(day2)).toBe(true);
    expect(bodies()).toEqual([{ first_visit: true }, { first_visit: false }]);
  });

  it('two overlapping calls (StrictMode, two effects) send one request', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    const [first, second] = await Promise.all([recordDailyVisit(day1), recordDailyVisit(day1)]);
    expect(first).toBe(true);
    expect(second).toBe(true);
    expect(bodies()).toEqual([{ first_visit: true }]);
  });

  it('a failed request is retried on the next load', async () => {
    vi.stubGlobal('localStorage', memoryStorage());
    fetchMock.mockImplementationOnce(async () => {
      throw new TypeError('offline');
    });
    await expect(recordDailyVisit(day1)).rejects.toThrow();
    expect(await recordDailyVisit(day1)).toBe(true);
    expect(bodies()[bodies().length - 1]).toEqual({ first_visit: true });
  });

  it('treats a browser with the retired Guest #N keys as returning, then removes them', async () => {
    const storage = memoryStorage();
    vi.stubGlobal('localStorage', storage);
    storage.setItem('abhijatri_guest_number', '42');
    storage.setItem('abhijatri_guest_last_visit', '2026-10-18');
    await recordDailyVisit(day1);
    expect(bodies()).toEqual([{ first_visit: false }]);
    expect(storage.getItem('abhijatri_guest_number')).toBeNull();
    expect(storage.getItem('abhijatri_guest_last_visit')).toBeNull();
    expect(storage.getItem('abhijatri_first_visit_on')).toBe('2026-10-18');
    expect(storage.getItem('abhijatri_last_visit_on')).toBe('2026-10-20');
  });

  it('still works with storage blocked (counted as new)', async () => {
    vi.stubGlobal('localStorage', blockedStorage);
    expect(await recordDailyVisit(day1)).toBe(true);
    expect(bodies()).toEqual([{ first_visit: true }]);
  });
});

describe('signOutGuest', () => {
  const day1 = new Date('2026-10-20T10:00:00Z');

  beforeEach(() => {
    vi.stubGlobal('document', { documentElement: { lang: 'en' } });
  });

  it('forgets the name only: tag, visit dates and scope stay, so it is not a new visitor', async () => {
    const storage = memoryStorage();
    vi.stubGlobal('localStorage', storage);
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const tag = await loadGuestTag();
    saveGuestName('Sadia');
    await recordDailyVisit(day1);

    signOutGuest();

    expect(loadGuestName()).toBeNull();
    expect(await loadGuestTag()).toBe(tag);
    expect(storage.getItem('abhijatri_first_visit_on')).toBe('2026-10-20');
    expect(await recordDailyVisit(day1)).toBe(false); // same day, same browser: not counted again
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('tolerates blocked storage', () => {
    vi.stubGlobal('localStorage', blockedStorage);
    expect(() => signOutGuest()).not.toThrow();
  });
});
