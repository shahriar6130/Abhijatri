import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getSession, login as loginRequest, logout as logoutRequest } from '../api/auth';
import type { AuthSession, StaffRole } from '../types';
import {
  loadGuestName,
  loadGuestTag,
  normalizeGuestName,
  recordDailyVisit,
  saveGuestName,
  signOutGuest,
  startAsNewGuest as resetGuest,
} from '../api/guests';

/**
 * Who is using the app. The interface adapts to it (for example, photo upload is offered only to
 * Verified Members), but it is never an authorization boundary: the API decides every permission
 * server-side (Review.md 1.1, PF 8).
 *
 * A visitor is a guest until they sign in (R04). Each browser has a guest tag
 * such as `1C669-J0TDY`, derived on the device from the guest scope secret
 * (Guest-Identity-and-Visits 3.1). A guest may give a name on `/guest`; it stays on this device for
 * 30 days after the last visit. The server only counts visits per day and never learns who visited.
 * The member and verified states are filled from `GET /api/v1/auth/session` when R04 lands;
 * nothing on the client can set them.
 */
export type Session =
  | { kind: 'guest'; displayName: string | null; guestTag: string | null }
  | { kind: 'member'; displayName: string; email: string; verifiedMember: boolean; role: StaffRole | null };

interface SessionContextValue {
  session: Session;
  isVerifiedMember: boolean;
  /** loading until the first answer from GET /auth/session; the page renders as a guest meanwhile. */
  status: 'loading' | 'ready';
  /** Signs in with the account service; throws ApiError (code INVALID_CREDENTIALS, EMAIL_NOT_VERIFIED, RATE_LIMITED, ...). */
  signIn: (email: string, password: string) => Promise<void>;
  refresh: () => Promise<void>;
  /** Saves the guest's name locally (a 30-day session on this device). */
  setGuestName: (name: string) => void;
  /** Forgets the stored name ("Not you?"); the tag and visit dates stay. */
  clearGuestName: () => void;
  /** A new scope secret and so a new tag. Visit dates are kept, so it is not a new visitor. */
  startAsNewGuest: () => Promise<void>;
  /**
   * Signs out. A guest has no server session, so this forgets the name only; the tag and visit
   * dates stay (Decisions 20 Oct 2026). When member accounts land (R04) a member sign-out will
   * also post `/auth/logout`.
   */
  signOut: () => void;
}

const SessionContext = createContext<SessionContextValue>({
  session: { kind: 'guest', displayName: null, guestTag: null },
  isVerifiedMember: false,
  status: 'loading',
  signIn: async () => undefined,
  refresh: async () => undefined,
  setGuestName: () => undefined,
  clearGuestName: () => undefined,
  startAsNewGuest: async () => undefined,
  signOut: () => undefined,
});

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [displayName, setDisplayName] = useState<string | null>(() => loadGuestName());
  const [guestTag, setGuestTag] = useState<string | null>(null);
  const [account, setAccount] = useState<Extract<AuthSession, { authenticated: true }> | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready'>('loading');

  useEffect(() => {
    let active = true;
    loadGuestTag()
      .then((tag) => {
        if (active) setGuestTag(tag);
      })
      .catch(() => undefined); // no WebCrypto (insecure origin): the badge shows without a tag
    // Ask the server who this is. A signed-in member is counted by the server (GET /auth/session);
    // everyone else is counted once per Dhaka day as a guest (API.md 5.14). Both are best effort:
    // a failure is retried on the next load and never blocks the page.
    getSession()
      .then((answer) => {
        if (!active) return;
        if (answer.authenticated) setAccount(answer);
        else void recordDailyVisit().catch(() => undefined);
      })
      .catch(() => {
        if (active) void recordDailyVisit().catch(() => undefined); // accounts unavailable: still a guest
      })
      .finally(() => {
        if (active) setStatus('ready');
      });
    return () => {
      active = false;
    };
  }, []);

  /** Re-reads the session, e.g. after a verification was approved. */
  const refresh = useCallback(async () => {
    const answer = await getSession().catch(() => null);
    if (answer?.authenticated) setAccount(answer);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const answer = await loginRequest(email, password);
    if (answer.authenticated) setAccount(answer);
  }, []);

  const setGuestName = useCallback((name: string) => {
    const normalized = normalizeGuestName(name);
    if (!normalized) return;
    saveGuestName(normalized);
    setDisplayName(normalized);
  }, []);

  const clearGuestName = useCallback(() => {
    saveGuestName(null);
    setDisplayName(null);
  }, []);

  const startAsNewGuest = useCallback(async () => {
    setGuestTag(await resetGuest());
  }, []);

  const signOut = useCallback(() => {
    if (account) {
      // End the server session; the page returns to the guest view whether or not the call succeeds.
      void logoutRequest()
        .catch(() => undefined)
        .finally(() => setAccount(null));
      return;
    }
    signOutGuest();
    setDisplayName(null);
  }, [account]);

  const value = useMemo<SessionContextValue>(
    () => ({
      session: account
        ? {
            kind: 'member',
            displayName: account.user.display_name,
            email: account.user.email,
            verifiedMember: account.verified_member, // an approved verification, not email verification alone
            role: account.role,
          }
        : { kind: 'guest', displayName, guestTag },
      isVerifiedMember: Boolean(account?.verified_member),
      status,
      signIn,
      refresh,
      setGuestName,
      clearGuestName,
      startAsNewGuest,
      signOut,
    }),
    [account, displayName, guestTag, status, signIn, refresh, setGuestName, clearGuestName, startAsNewGuest, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
};

export const useSession = (): SessionContextValue => useContext(SessionContext);
