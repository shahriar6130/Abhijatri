import { afterEach, describe, expect, it, vi } from 'vitest';
import { readStored, writeStored } from './safeStorage';

describe('safeStorage (UI-Architecture U12)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns null and does not throw when storage access is blocked', () => {
    vi.stubGlobal('window', {
      get localStorage(): Storage {
        throw new DOMException('Access is denied for this document.', 'SecurityError');
      },
    });
    expect(readStored('abhijatri_lang')).toBeNull();
    expect(() => writeStored('abhijatri_lang', 'en')).not.toThrow();
  });

  it('reads and writes when storage works', () => {
    const data = new Map<string, string>();
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => data.get(key) ?? null,
        setItem: (key: string, value: string) => void data.set(key, value),
      },
    });
    writeStored('abhijatri_theme', 'dark');
    expect(readStored('abhijatri_theme')).toBe('dark');
  });

  it('survives a full quota on write', () => {
    vi.stubGlobal('window', {
      localStorage: {
        getItem: () => null,
        setItem: () => {
          throw new DOMException('Quota exceeded', 'QuotaExceededError');
        },
      },
    });
    expect(() => writeStored('abhijatri_lang', 'bn')).not.toThrow();
  });
});
