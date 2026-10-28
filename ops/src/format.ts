import type { Lang, SeriesBlock } from './types';

/** A missing number is shown as a dash, never 0 (System-Monitoring-Dashboard R5). */
export function formatValue(value: number | string | null | undefined, lang: Lang): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  return new Intl.NumberFormat(lang === 'bn' ? 'bn-BD' : 'en-US', { maximumFractionDigits: 1 }).format(value);
}

export function formatTime(iso: string | null, lang: Lang): string {
  if (!iso) return lang === 'bn' ? 'পাওয়া যায়নি' : 'unavailable';
  return new Intl.DateTimeFormat(lang === 'bn' ? 'bn-BD' : 'en-GB', {
    timeZone: 'Asia/Dhaka',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

/**
 * SVG polyline segments for a series. A `null` point breaks the line (a gap, not a zero), so
 * days without data are visible as missing.
 */
export function seriesPaths(points: SeriesBlock['points'], width: number, height: number): string[] {
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  const max = Math.max(1, ...values);
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const segments: string[] = [];
  let current: string[] = [];
  points.forEach((point, index) => {
    if (point.value === null) {
      if (current.length) segments.push(current.join(' '));
      current = [];
      return;
    }
    const x = (index * step).toFixed(1);
    const y = (height - (point.value / max) * height).toFixed(1);
    current.push(`${x},${y}`);
  });
  if (current.length) segments.push(current.join(' '));
  return segments;
}
