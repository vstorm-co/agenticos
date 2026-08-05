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
  return isSafeReturnPath(returnTo) ? returnTo : ROUTES.DASHBOARD;
}

/**
 * Only a same-origin path may be honoured. A value with a scheme
 * ("https://evil.example"), a protocol-relative one ("//evil.example") or a
 * backslash variant ("/\evil.example", which browsers normalise to "//")
 * would turn ?returnTo= into an open redirect off the login form.
 *
 * Both checks are load-bearing. The regex alone misses control characters:
 * the URL parser strips tab, LF and CR before parsing, so "/\t/evil.example"
 * resolves to "https://evil.example". The origin check alone would accept a
 * relative path like "agents", which resolves same-origin but against
 * wherever the visitor happens to stand.
 */
function isSafeReturnPath(path: string | null | undefined): path is string {
  return (
    typeof path === "string" &&
    /^\/(?![/\\])/.test(path) &&
    new URL(path, window.location.origin).origin === window.location.origin
  );
}
