/**
 * Carrying `?returnTo=` across the provider round trip.
 *
 * A visitor at `/login?returnTo=/agents/a-1` who signs in with the password form
 * resumes the deep link; one who clicked a provider button landed on the
 * dashboard, so which button they picked decided where they ended up (#135).
 * Nothing carried the path: the browser leaves this origin for the provider and
 * comes back to `/auth/callback?code=`, and neither hop has room for it.
 *
 * `sessionStorage`, not the OAuth `state` parameter, because the whole trip
 * starts and ends in the same tab on this origin - so a value written beside the
 * provider link is there to be read when the browser returns, and no server has
 * to hold it. A flow that ends somewhere else (a link opened in a new tab, a
 * different browser) finds nothing and lands on the dashboard, which is where it
 * landed before.
 *
 * Every read consumes the value. One left behind would resume a deep link
 * somebody had already abandoned, on the next sign-in from that tab.
 *
 * Nothing here validates the path: {@link postSignInDestination} is the one
 * place that decides whether a return path is safe to honour, and a second copy
 * of that rule is a second answer to it.
 */

const KEY = "oauthReturnTo";

/**
 * Remember where to land, or forget a path from an earlier attempt.
 *
 * Always one or the other. Leaving a stale value in place is how a second
 * sign-in with no deep link resumes the first one's.
 */
export function rememberReturnTo(path: string | null | undefined): void {
  try {
    if (path) {
      window.sessionStorage.setItem(KEY, path);
    } else {
      window.sessionStorage.removeItem(KEY);
    }
  } catch {
    // A browser that refuses site data still has to be able to sign in; the
    // cost is landing on the dashboard.
  }
}

/** The remembered path, removed as it is read. */
export function takeReturnTo(): string | null {
  try {
    const path = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    return path;
  } catch {
    return null;
  }
}
