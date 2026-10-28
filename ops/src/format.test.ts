import { describe, expect, it } from 'vitest';
import { formatValue, seriesPaths } from './format';

describe('formatValue', () => {
  it('shows a dash for a missing number, never 0', () => {
    expect(formatValue(null, 'en')).toBe('—');
    expect(formatValue(undefined, 'bn')).toBe('—');
    expect(formatValue(0, 'en')).toBe('0');
  });

  it('uses Bangla digits in Bangla', () => {
    expect(formatValue(12, 'bn')).toBe('১২');
  });
});

describe('seriesPaths', () => {
  it('breaks the line at days without data', () => {
    const points = [
      { date: '2026-10-18', value: 2 },
      { date: '2026-10-19', value: null },
      { date: '2026-10-20', value: 4 },
      { date: '2026-10-21', value: 0 },
    ];
    const segments = seriesPaths(points, 300, 100);
    expect(segments).toHaveLength(2);
    expect(segments[0]).toBe('0.0,50.0');
    expect(segments[1]).toBe('200.0,0.0 300.0,100.0');
  });

  it('draws nothing when every day is missing', () => {
    expect(seriesPaths([{ date: '2026-10-21', value: null }], 300, 100)).toEqual([]);
  });
});
