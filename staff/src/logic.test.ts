import { describe, expect, it, vi } from 'vitest';
import { StaffError } from './api';
import { INBOX_POLL_MS, QUEUE_POLL_MS, RELOAD_CODES, REASONS, decisionsFor, keepFresh, errorText, formatCountdown, newIdempotencyKey, qrImageSource, reportMoves, secondsLeft } from './logic';

describe('decisionsFor (mirrors the server state machine)', () => {
  it('offers publish, reject or ask for changes for a waiting review', () => {
    expect(decisionsFor('PENDING')).toEqual(['PUBLISH', 'REJECT', 'REQUEST_CHANGES']);
    expect(decisionsFor('UNDER_REVIEW')).toEqual(['PUBLISH', 'REJECT', 'REQUEST_CHANGES']);
  });
  it('offers hide for a published review and restore for a hidden one', () => {
    expect(decisionsFor('PUBLISHED')).toEqual(['HIDE']);
    expect(decisionsFor('HIDDEN')).toEqual(['RESTORE']);
  });
  it('offers nothing for final states', () => {
    // CHANGES_REQUESTED is the author's turn: staff cannot decide again until the author edits.
    for (const state of ['REJECTED', 'WITHDRAWN', 'DELETED', 'CHANGES_REQUESTED', 'nonsense']) expect(decisionsFor(state)).toEqual([]);
  });
  it('has at least one reason for every decision', () => {
    for (const decision of ['PUBLISH', 'REJECT', 'HIDE', 'RESTORE', 'REQUEST_CHANGES'] as const) expect(REASONS[decision].length).toBeGreaterThan(0);
  });
  it('never offers ask-for-changes on a published, hidden or finished review', () => {
    for (const state of ['PUBLISHED', 'HIDDEN', 'REJECTED', 'WITHDRAWN']) expect(decisionsFor(state)).not.toContain('REQUEST_CHANGES');
  });
  it('gives every reason a Bangla and an English text and a 2 to 60 character code', () => {
    for (const list of Object.values(REASONS)) for (const r of list) {
      expect(r.bn.length).toBeGreaterThan(0);
      expect(r.en.length).toBeGreaterThan(0);
      expect(r.code.length).toBeGreaterThanOrEqual(2);
      expect(r.code.length).toBeLessThanOrEqual(60);
    }
  });
});

describe('keeping staff screens fresh (no notification or queue delay)', () => {
  it('polls the queue at least every 10 seconds and the inbox at least every 30', () => {
    expect(QUEUE_POLL_MS).toBeLessThanOrEqual(10_000);
    expect(INBOX_POLL_MS).toBeLessThanOrEqual(30_000);
  });

  it('loads at once, on a timer while visible, and when the tab is shown again, and stops on cleanup', () => {
    const listeners: Record<string, () => void> = {};
    vi.useFakeTimers();
    const doc = { hidden: false, addEventListener: (n: string, f: () => void) => (listeners[n] = f), removeEventListener: (n: string) => delete listeners[n] };
    const win = { setInterval: (f: () => void, ms: number) => setInterval(f, ms), clearInterval: (id: number) => clearInterval(id), addEventListener: (n: string, f: () => void) => (listeners[`w${n}`] = f), removeEventListener: (n: string) => delete listeners[`w${n}`] };
    vi.stubGlobal('document', doc);
    vi.stubGlobal('window', win);
    const load = vi.fn();
    const stop = keepFresh(load, 5_000);
    expect(load).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(5_000);
    expect(load).toHaveBeenCalledTimes(2);
    doc.hidden = true; // a hidden tab does not poll
    vi.advanceTimersByTime(15_000);
    expect(load).toHaveBeenCalledTimes(2);
    doc.hidden = false;
    listeners.visibilitychange(); // shown again: refresh at once
    expect(load).toHaveBeenCalledTimes(3);
    listeners.wfocus();
    expect(load).toHaveBeenCalledTimes(4);
    stop();
    vi.advanceTimersByTime(20_000);
    expect(load).toHaveBeenCalledTimes(4);
    expect(Object.keys(listeners)).toHaveLength(0);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});

describe('reportMoves', () => {
  it('follows the report transition table', () => {
    expect(reportMoves('open')).toEqual(['in_review', 'actioned', 'dismissed']);
    expect(reportMoves('in_review')).toEqual(['actioned', 'dismissed']);
    expect(reportMoves('actioned')).toEqual([]);
    expect(reportMoves('dismissed')).toEqual([]);
  });
});

describe('lease countdown', () => {
  const now = Date.parse('2026-10-27T10:00:00Z');
  it('counts down and never goes negative', () => {
    expect(secondsLeft('2026-10-27T10:04:30Z', now)).toBe(270);
    expect(secondsLeft('2026-10-27T09:59:00Z', now)).toBe(0);
    expect(secondsLeft(null, now)).toBeNull();
    expect(secondsLeft(undefined, now)).toBeNull();
  });
  it('formats minutes and seconds', () => {
    expect(formatCountdown(270)).toBe('4:30');
    expect(formatCountdown(5)).toBe('0:05');
    expect(formatCountdown(null)).toBe('—');
  });
});

describe('qrImageSource', () => {
  it('encodes the raw SVG that Supabase returns so the browser can draw it', () => {
    const raw = `data:image/svg+xml;utf-8,<svg xmlns="http://www.w3.org/2000/svg" fill="#fff"><path d="M0 0"/></svg>`;
    const source = qrImageSource(raw) as string;
    expect(source.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
    expect(source).not.toContain('<');
    expect(source).not.toContain('#');
    expect(decodeURIComponent(source.split(',')[1])).toContain('<svg');
  });
  it('draws a bare SVG document, as the API returns it', () => {
    const raw = '<?xml version="1.0"?>\n<!-- Generated by SVGo -->\n<svg width="207" height="207" xmlns="http://www.w3.org/2000/svg"><rect fill="#000"/></svg>';
    const source = qrImageSource(raw) as string;
    expect(source.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
    expect(decodeURIComponent(source.split(',')[1]).startsWith('<svg')).toBe(true);
  });
  it('accepts a base64 image and refuses anything else', () => {
    expect(qrImageSource('data:image/png;base64,iVBORw0KGgo=')).toBe('data:image/png;base64,iVBORw0KGgo=');
    expect(qrImageSource('https://evil.example/qr.png')).toBeNull();
    expect(qrImageSource('javascript:alert(1)')).toBeNull();
    expect(qrImageSource(null)).toBeNull();
  });
});

describe('idempotency keys', () => {
  it('are unique and accepted by the API pattern', () => {
    const a = newIdempotencyKey();
    expect(a).not.toBe(newIdempotencyKey());
    expect(a).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
  });
});

describe('errorText', () => {
  it('explains the codes staff meet, in both languages', () => {
    for (const code of ['LEASE_LOST', 'REVIEW_VERSION_CONFLICT', 'TRANSITION_NOT_ALLOWED', 'FORBIDDEN', 'MFA_REQUIRED', 'REAUTH_REQUIRED', 'LAST_SUPERADMIN', 'NETWORK_ERROR']) {
      const en = errorText(new StaffError(409, code), 'en');
      const bn = errorText(new StaffError(409, code), 'bn');
      expect(en).not.toContain(code === 'NETWORK_ERROR' ? '@@' : `Error: ${code}`);
      expect(bn).not.toBe(en);
    }
  });
  it('falls back to the code for an unknown one, and to a plain line for a non-API error', () => {
    expect(errorText(new StaffError(500, 'SOMETHING_NEW'), 'en')).toBe('Error: SOMETHING_NEW');
    expect(errorText(new Error('boom'), 'en')).toBe('Something went wrong.');
  });
  it('knows which errors mean "reload"', () => {
    expect(RELOAD_CODES.has('LEASE_LOST')).toBe(true);
    expect(RELOAD_CODES.has('RATE_LIMITED')).toBe(false);
  });
});

describe('verificationMoves and enforcementActions', () => {
  it('mirror the server transition tables', async () => {
    const { verificationMoves, enforcementActions } = await import('./logic');
    expect(verificationMoves('submitted', 'moderator')).toEqual(['in_review', 'escalated']);
    expect(verificationMoves('in_review', 'moderator')).toContain('approved');
    expect(verificationMoves('escalated', 'moderator')).toEqual([]);
    expect(verificationMoves('escalated', 'superadmin')).toEqual(['approved', 'rejected']);
    expect(verificationMoves('approved', 'superadmin')).toEqual([]);
    expect(enforcementActions('taken_down')).toEqual(['remove', 'restore']);
    expect(enforcementActions('removed')).toEqual(['restore']);
    expect(enforcementActions('open')).toEqual(['close']);
    expect(enforcementActions('closed')).toEqual([]);
  });
});
