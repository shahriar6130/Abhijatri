/**
 * Ops API client (System-Monitoring-Dashboard 3.1 and 5).
 *
 * The token travels only in the Authorization header and is kept in sessionStorage, so it is
 * gone when the tab closes. It is never put in a URL, a cookie or localStorage.
 */

import type { CatalogueEntry, Days, Overview, PanelData } from './types';

const TOKEN_KEY = 'abhijatri_ops_token';
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '');

export class OpsError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

export function loadToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string | null): void {
  try {
    if (token === null) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // storage blocked: the token lives in memory for this page only
  }
}

async function request<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/v1/ops${path}`, {
      ...init,
      cache: 'no-store',
      credentials: 'omit',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    });
  } catch {
    throw new OpsError(0, 'NETWORK');
  }
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    try {
      code = ((await response.json()) as { error?: { code?: string } }).error?.code ?? code;
    } catch {
      // non-JSON error body
    }
    throw new OpsError(response.status, code);
  }
  return (await response.json()) as T;
}

export const getCatalogue = (token: string) => request<{ panels: CatalogueEntry[] }>(token, '/panels');

/** Panels in catalogue order; a panel missing from the catalogue keeps its place after the rest. */
export function orderByCatalogue(panels: PanelData[], catalogue: CatalogueEntry[]): PanelData[] {
  const rank = new Map(catalogue.map((entry, index) => [entry.id, index]));
  return [...panels].sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity));
}

export const getOverview = (token: string, days: Days) => request<Overview>(token, `/overview?days=${days}`);

export const getPanel = (token: string, id: string, days: Days) =>
  request<PanelData>(token, `/panels/${encodeURIComponent(id)}?days=${days}`);

export const runRollup = (token: string) =>
  request<{ rolled_up: string[] }>(token, '/jobs/visit-rollup', { method: 'POST' });

export function describeError(error: unknown, lang: 'bn' | 'en'): string {
  const t = (bn: string, en: string) => (lang === 'bn' ? bn : en);
  if (!(error instanceof OpsError)) return t('অজানা ত্রুটি।', 'Unknown error.');
  // A blocked CORS preflight also surfaces as a network error in the browser.
  if (error.status === 0)
    return t(
      `API-তে পৌঁছানো যায়নি (${API_BASE})। সম্ভাব্য কারণ: API বন্ধ, API-তে এখনো ops সংস্করণ ডিপ্লয় হয়নি, অথবা CORS_ALLOWED_ORIGINS-এ এই ড্যাশবোর্ডের ঠিকানা নেই (${window.location.origin})।`,
      `Could not reach the API at ${API_BASE}. Likely causes: the API is down, the deployed API predates the ops routes, or CORS_ALLOWED_ORIGINS does not include this dashboard (${window.location.origin}).`,
    );
  if (error.status === 401) return t('টোকেন সঠিক নয়।', 'The token is not valid.');
  if (error.status === 404)
    return t(
      'Ops API বন্ধ আছে: সার্ভারে OPS_DASHBOARD_TOKEN সেট করা নেই।',
      'The ops API is off: OPS_DASHBOARD_TOKEN is not set on the server.',
    );
  if (error.status === 429) return t('অনেকবার ভুল টোকেন। এক ঘণ্টা পরে চেষ্টা করুন।', 'Too many failed attempts. Try again within the hour.');
  if (error.status === 503) return t('Redis পাওয়া যাচ্ছে না।', 'Redis is not reachable.');
  return t(`ত্রুটি: ${error.code}`, `Error: ${error.code}`);
}
