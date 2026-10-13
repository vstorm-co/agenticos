import { isSafeReturnPath } from "@/lib/safe-return-path";
import { ROUTES } from "@/lib/constants";

/**
 * Where a fresh session lands: the deep link the visitor was headed to when
 * it is safe to honour, the dashboard otherwise.
 *
 * Every sign-in path - password, the OAuth callback, the magic link - resolves
 * its redirect here. Each of them establishes a session by a different route,
 * which is exactly why the destination must not be decided in three places:
 * the answers drift, and which door somebody came through starts deciding
 * where they land.
 *
 * The default is deliberately the same for every role. What a role may not
 * see is handled by not rendering the widget, never by a different landing
 * page - a role fork here quietly splits one product into two.
 */
export function postSignInDestination(returnTo?: string | null): string {
  return isSafeReturnPath(returnTo, window.location.origin) ? returnTo : ROUTES.DASHBOARD;
}

/**
 * Go to where a fresh session lands, by whichever navigation survives the path.
 *
 * `next@16.2`'s segment cache appends a fragment a second time on a soft
 * navigation - `/path#x` becomes `/path#x#x` in a production build - so a
 * destination carrying one has to load the document instead. The branches are
 * **not** equivalent: a document load drops the in-memory access token, which is
 * re-adopted from `/auth/me` on arrival, and anything the caller runs afterwards
 * fires into an unloading page.
 *
 * Here rather than at each sign-in path, for the reason
 * {@link postSignInDestination} is: the password form had this branch and the
 * OAuth callback did not, so a deep link with an anchor behaved differently
 * depending on which button somebody pressed - which is the drift #135 is
 * about, one axis over.
 */
export function goToDestination(destination: string, navigate: (href: string) => void): void {
  if (destination.includes("#")) {
    window.location.assign(destination);
    return;
  }
  navigate(destination);
}
