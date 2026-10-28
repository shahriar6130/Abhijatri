import { describe, expect, it } from 'vitest';
import { categoryOf, linkTarget, mergeNewest } from './notifications';
import type { AppNotification } from '../types';

const item = (id: string, created_at: string, kind = 'content.published'): AppNotification => ({
  id,
  kind,
  critical: false,
  title: { bn: 't', en: 't' },
  body: { bn: 'b', en: 'b' },
  link: null,
  created_at,
  read: false,
});

describe('notification helpers', () => {
  it('merges live items with a refetch, newest first and without duplicates', () => {
    const current = [item('a', '2026-10-28T08:00:00Z'), item('b', '2026-10-28T07:00:00Z')];
    const merged = mergeNewest(current, [item('c', '2026-10-28T09:00:00Z'), item('a', '2026-10-28T08:00:00Z')]);
    expect(merged.map((n) => n.id)).toEqual(['c', 'a', 'b']);
  });

  it('takes the category from the kind when the server does not send one', () => {
    expect(categoryOf(item('x', '2026-10-28T08:00:00Z', 'appeal.received'))).toBe('appeal');
    expect(categoryOf({ kind: 'content.rejected', category: 'content' })).toBe('content');
  });

  it('sends staff links to the staff dashboard and refuses anything that is not a route', () => {
    expect(linkTarget('staff:/', 'https://staff.example/')).toEqual({ external: 'https://staff.example/' });
    expect(linkTarget('/account/appeals', 'x')).toEqual({ internal: '/account/appeals' });
    expect(linkTarget('https://evil.example', 'x')).toBeNull();
    expect(linkTarget(null, 'x')).toBeNull();
  });
});
