import { isSafeReturnPath } from "./safe-return-path";

/**
 * The origin a destination is only *shape-checked* against.
 *
 * Not `window.location.origin`: both callers are client components that Next
 * also renders on the server, where there is no window. `.invalid` is reserved
 * (RFC 2606), so it can never be a deployment's own origin - and the answer
 * does not depend on which origin is passed, only on whether the value
 * resolves away from it.
 */
const SHAPE_ONLY_ORIGIN = "https://console.invalid";

/**
 * Whether a notification's destination is one of this console's own pages.
 *
 * `context_url` holds a path (`/agents/{id}?org={uuid}`), and a path is what
 * the router navigates as a sub-route: the page swaps under the layout that is
 * already mounted, instead of reloading the whole document to reach somewhere
 * the reader is usually already standing. Two shapes are not: a row written
 * before the column changed meaning, which still carries `FRONTEND_URL` plus
 * the path, and anything protocol-relative. Both keep the plain anchor every
 * row used to have.
 *
 * `isSafeReturnPath` rather than a second `startsWith("/")`, because
 * `safe-return-path.ts` says in as many words why the second copy is the one
 * that ends up weaker - it is the copy that accepts `/\t/evil.example`. Note
 * that the fallback for a value this refuses is still an anchor, which would
 * follow it: that is safe only because `context_url` is server-built at a
 * dozen curated call sites and never carries anything a caller supplied. If it
 * ever does, the anchor branch has to go, not just this one.
 */
export function isInAppPath(contextUrl: string): boolean {
  return isSafeReturnPath(contextUrl, SHAPE_ONLY_ORIGIN);
}
