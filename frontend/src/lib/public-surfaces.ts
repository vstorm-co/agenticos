/**
 * The routes served to somebody who is not a member of any organization.
 *
 * A hosted page (`/e/<key>`) and a shared conversation (`/shared/<token>`) are the
 * only two, and what makes them a category rather than two paths is that nobody
 * signs in on either: there is no session, no organization header, and the visitor
 * is identified - if at all - by one `localStorage` key of their own browser's
 * making. Anything written for a member is therefore wrong here by construction,
 * not merely unhelpful, which is what the cookie banner demonstrated (#644).
 */
const PUBLIC_SURFACES = ["/e/", "/shared/"] as const;

/**
 * Whether this path is one of them.
 *
 * Takes a path **without** the locale prefix, which is what `usePathname` from
 * `@/lib/locale-navigation` answers with. Reading `next/navigation`'s instead would
 * miss every Polish visitor, because `/pl/e/abc` starts with neither prefix.
 */
export function isPublicSurface(pathname: string): boolean {
  return PUBLIC_SURFACES.some((surface) => pathname.startsWith(surface));
}
