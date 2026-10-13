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

import { ROUTES } from "@/lib/constants";
import { invitationTokenFrom } from "@/lib/invitation-links";

const KEY = "oauthReturnTo";

/**
 * Remember a path, forget one, or leave the store as it is.
 *
 * A string is remembered, `null` forgets a stale one (a second sign-in with no
 * deep link must not resume the first one's), and `undefined` touches nothing -
 * which is what a retry passes, so the deep link it wrote before the failed attempt
 * stays without being read back out and written again.
 *
 * A credential-bearing invitation deep link is never what gets stored: the token is
 * exchanged for an `httpOnly` handle before sign-in (#1414), so a path still carrying
 * one is replaced with its credential-free landing rather than written to a store a
 * script can read. By the time a value reaches here it should already be
 * `/invitations/pending`; this guarantees a raw token cannot land in `sessionStorage`
 * even if one does not.
 */
export function rememberReturnTo(path: string | null | undefined): void {
  if (path === undefined) return;
  try {
    const safe = path && invitationTokenFrom(path) ? ROUTES.INVITATION_PENDING : path;
    if (safe) {
      window.sessionStorage.setItem(KEY, safe);
    } else {
      window.sessionStorage.removeItem(KEY);
    }
  } catch {
    // A browser that refuses site data still has to be able to sign in; the
    // cost is landing on the dashboard.
  }
}

/**
 * What an attempt started from this URL should do with the remembered path.
 *
 * `?returnTo=` when the visitor arrived with one - store it. Otherwise clear a
 * stale one, *except* on a retry: a failed provider attempt comes back to
 * `/login?error=…` with the deep link gone from the URL and the one written before
 * the attempt still in storage, so it answers `undefined` there - leave it in place
 * rather than read it back out and rewrite it. Only the OAuth callback and the
 * provider redirect mint that `error`, which is what makes it a reliable "this is
 * the second attempt at the same thing".
 */
export function returnToForAttempt(search: {
  get: (name: string) => string | null;
}): string | null | undefined {
  const named = search.get("returnTo");
  if (named) return named;
  return search.get("error") ? undefined : null;
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
