import type { AppNotification } from '../types';

/** Bilingual names of notification categories (the first part of the kind). */
export const CATEGORY_LABEL: Record<string, [string, string]> = {
  content: ['রিভিউ', 'Review'],
  account: ['অ্যাকাউন্ট', 'Account'],
  verification: ['যাচাই', 'Verification'],
  appeal: ['আপিল', 'Appeal'],
  report: ['রিপোর্ট', 'Report'],
  security: ['নিরাপত্তা', 'Security'],
  moderation: ['মডারেশন', 'Moderation'],
  staff: ['কর্মী', 'Staff'],
  notification: ['সিস্টেম', 'System'],
};

export function categoryOf(item: Pick<AppNotification, 'kind' | 'category'>): string {
  return item.category ?? item.kind.split('.', 1)[0];
}

/** Add newer items at the top without duplicates (a live event may repeat what a refetch returned). */
export function mergeNewest(current: AppNotification[], incoming: AppNotification[], limit = 50): AppNotification[] {
  const seen = new Set<string>();
  return [...incoming, ...current]
    .filter((item) => (seen.has(item.id) ? false : (seen.add(item.id), true)))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, limit);
}

/** Staff links (`staff:/…`) open the separate staff dashboard; others are routes of this app. */
export function linkTarget(link: string | null, staffBase: string): { internal: string } | { external: string } | null {
  if (!link) return null;
  if (link.startsWith('staff:')) return { external: `${staffBase.replace(/\/+$/, '')}${link.slice('staff:'.length)}` };
  return link.startsWith('/') ? { internal: link } : null;
}
