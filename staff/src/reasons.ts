import { useEffect, useState } from 'react';
import { getReasonCodes } from './api';
import type { ReasonCatalogue } from './types';

/**
 * The reason codes the server accepts (`GET /admin/reason-codes`, Moderation spec P-06). Loaded once per page and
 * shared; until it arrives, or if it cannot be loaded, the screens use the built-in lists in `logic.ts`, which the
 * backend tests keep in line with the server's own list.
 */
let cached: ReasonCatalogue | null = null;
let pending: Promise<ReasonCatalogue | null> | null = null;

export function loadReasonCatalogue(): Promise<ReasonCatalogue | null> {
  if (cached) return Promise.resolve(cached);
  pending ??= getReasonCodes()
    .then((answer) => (cached = answer.groups))
    .catch(() => null)
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function useReasonCatalogue(): ReasonCatalogue | null {
  const [catalogue, setCatalogue] = useState<ReasonCatalogue | null>(cached);
  useEffect(() => {
    let live = true;
    void loadReasonCatalogue().then((groups) => {
      if (live && groups) setCatalogue(groups);
    });
    return () => {
      live = false;
    };
  }, []);
  return catalogue;
}

/** For tests: forget what was loaded. */
export function resetReasonCatalogue(): void {
  cached = null;
  pending = null;
}
