import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { BlockList, columnLabel } from './Blocks';
import type { Block } from './types';

const label = { bn: 'লেবেল', en: 'Label' };

const render = (blocks: Block[], lang: 'bn' | 'en' = 'en') => renderToStaticMarkup(<BlockList blocks={blocks} lang={lang} />);

describe('BlockList', () => {
  it('renders a stat, a status, a series and a table from the four block types', () => {
    const html = render([
      { type: 'stat', key: 'a', label: { bn: 'অপেক্ষমাণ', en: 'Pending' }, value: 12, limit: 500, level: 'ok' },
      { type: 'status', key: 'b', label: { bn: 'লেখা', en: 'Guest writes' }, value: 'open', level: 'ok' },
      { type: 'series', key: 'c', label: label, points: [{ date: '2026-10-20', value: 4 }, { date: '2026-10-21', value: 6 }] },
      { type: 'table', key: 'd', label: label, columns: ['status', 'count'], rows: [['PUBLISHED', 31]] },
    ]);
    expect(html).toContain('Pending');
    expect(html).toContain('Guest writes');
    expect(html).toContain('PUBLISHED');
  });

  it('shows a dash, never 0, for a missing stat', () => {
    expect(render([{ type: 'stat', key: 'a', label, value: null, level: 'ok' }])).toContain('—');
  });

  it('uses Bangla labels and digits in Bangla', () => {
    const html = render([{ type: 'stat', key: 'a', label: { bn: 'অপেক্ষমাণ', en: 'Pending' }, value: 12, level: 'ok' }], 'bn');
    expect(html).toContain('অপেক্ষমাণ');
    expect(html).toContain('১২');
  });

  it('translates known table headers and leaves unknown ones as sent', () => {
    expect(columnLabel('status', 'bn')).toBe('অবস্থা');
    expect(columnLabel('status', 'en')).toBe('Status');
    expect(columnLabel('custom_column', 'bn')).toBe('custom_column');
    const html = render([{ type: 'table', key: 'd', label, columns: ['route', 'count'], rows: [['/x', 2]] }], 'bn');
    expect(html).toContain('রুট');
    expect(html).toContain('সংখ্যা');
  });

  it('says so when a table is empty', () => {
    expect(render([{ type: 'table', key: 'd', label, columns: ['status'], rows: [] }])).toContain('None');
  });
});
