/**
 * localStorage that never throws. Private windows, blocked site data and storage quotas make the
 * Storage API throw; a preference read must never stop the app from rendering (UI-Architecture U12).
 */
export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Not persisted; the choice still applies for this page load.
  }
}
