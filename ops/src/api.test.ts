import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  OpsError,
  describeError,
  getCatalogue,
  getOverview,
  loadToken,
  orderByCatalogue,
  runRollup,
  saveToken,
} from './api';
import type { CatalogueEntry, PanelData } from './types';

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token storage', () => {
  it('keeps the token in sessionStorage only, never localStorage', () => {
    const session = memoryStorage();
    const local = memoryStorage();
    vi.stubGlobal('sessionStorage', session);
    vi.stubGlobal('localStorage', local);
    saveToken('secret-token');
    expect(loadToken()).toBe('secret-token');
    expect(local.length).toBe(0);
    saveToken(null);
    expect(loadToken()).toBeNull();
  });

  it('survives blocked storage', () => {
    const blocked = {
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
    vi.stubGlobal('sessionStorage', blocked);
    expect(() => saveToken('x')).not.toThrow();
    expect(loadToken()).toBeNull();
  });
});

describe('requests', () => {
  it('sends the token only in the Authorization header, with no cookies and no caching', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ panels: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await getCatalogue('tok-123');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/v1/ops/panels');
    expect(url).not.toContain('tok-123');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
    expect(init.credentials).toBe('omit');
    expect(init.cache).toBe('no-store');
  });

  it('asks for the chosen number of days', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ generated_at: '', days: 90, panels: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await getOverview('t', 90);
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toContain('/overview?days=90');
  });

  it('POSTs the roll-up', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ rolled_up: ['2026-10-26'] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await runRollup('t')).toEqual({ rolled_up: ['2026-10-26'] });
    expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].method).toBe('POST');
  });

  it('turns an error body into an OpsError with the API code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'AUTH_REQUIRED' } }), { status: 401 })));
    await expect(getCatalogue('bad')).rejects.toMatchObject({ status: 401, code: 'AUTH_REQUIRED' });
  });

  it('reports a network failure as status 0', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    await expect(getCatalogue('t')).rejects.toMatchObject({ status: 0, code: 'NETWORK' });
  });
});

describe('describeError', () => {
  it('explains each status in both languages', () => {
    vi.stubGlobal('window', { location: { origin: 'https://ops.example' } });
    expect(describeError(new OpsError(401, 'x'), 'en')).toMatch(/not valid/);
    expect(describeError(new OpsError(404, 'x'), 'en')).toMatch(/OPS_DASHBOARD_TOKEN/);
    expect(describeError(new OpsError(429, 'x'), 'bn')).toMatch(/টোকেন/);
    expect(describeError(new OpsError(503, 'x'), 'en')).toMatch(/Redis/);
    expect(describeError(new OpsError(0, 'NETWORK'), 'en')).toMatch(/CORS_ALLOWED_ORIGINS/);
    expect(describeError(new Error('boom'), 'en')).toBe('Unknown error.');
  });
});

describe('orderByCatalogue', () => {
  const panel = (id: string) => ({ id }) as PanelData;
  const entry = (id: string) => ({ id }) as CatalogueEntry;

  it('follows the catalogue order and keeps unknown panels last', () => {
    const ordered = orderByCatalogue([panel('z'), panel('b'), panel('a')], [entry('a'), entry('b')]);
    expect(ordered.map((p) => p.id)).toEqual(['a', 'b', 'z']);
  });

  it('keeps the given order when the catalogue is empty', () => {
    expect(orderByCatalogue([panel('b'), panel('a')], []).map((p) => p.id)).toEqual(['b', 'a']);
  });
});
