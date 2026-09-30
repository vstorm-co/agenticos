/**
 * One refresh at a time across every tab of this browser.
 *
 * The refresh cookie is shared by all tabs, and the backend rotates it on each
 * use: a second tab presenting it a moment after the first presents a token
 * that was just spent. Two paths can spend it - `/api/auth/refresh` after a 401,
 * and `/api/auth/me`, which refreshes on the server once the 15-minute access
 * cookie is gone - and a laptop waking from sleep fires every tab's timer at
 * once. The Web Locks API serializes them: the tab that waits sends its request
 * after the first tab's `Set-Cookie` has landed, so it carries the new cookie.
 *
 * `navigator.locks` exists only in a secure context. A deployment served over
 * plain HTTP runs `fn` unserialized, and the backend's reuse grace window is
 * what keeps that case signed in.
 */

const LOCK_NAME = "agenticos-auth-refresh";
const REFRESHED_AT_KEY = "agenticos:auth-refreshed-at";

// A refresh another tab finished this recently has already rotated the cookies
// this tab is about to send, so this tab's own refresh would only spend them again.
const RECENT_REFRESH_MS = 10_000;

export function withAuthLock<T>(fn: () => Promise<T>): Promise<T> {
  if (typeof navigator === "undefined" || !("locks" in navigator) || !navigator.locks) {
    return fn();
  }
  return navigator.locks.request(LOCK_NAME, fn);
}

/** Record that this tab just refreshed, for the others to read. */
export function markRefreshed(): void {
  try {
    localStorage.setItem(REFRESHED_AT_KEY, String(Date.now()));
  } catch {
    // Storage blocked: the other tabs refresh for themselves, under the lock.
  }
}

/** Whether some tab refreshed within the last few seconds. */
export function refreshedRecently(): boolean {
  try {
    const at = Number(localStorage.getItem(REFRESHED_AT_KEY));
    return Number.isFinite(at) && at > 0 && Date.now() - at < RECENT_REFRESH_MS;
  } catch {
    return false;
  }
}
