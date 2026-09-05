/**
 * Whether a remembered destination is one of this app's own paths.
 *
 * The one guard every `returnTo` goes through - the sign-in landing and the MCP
 * OAuth consent alike. Written once because the second copy is the one that ends
 * up weaker: the MCP guard was three `startsWith` checks and accepted
 * `/\t/evil.example`, which is precisely the case this function's other caller
 * had already documented.
 *
 * A value with a scheme (`https://evil.example`), a protocol-relative one
 * (`//evil.example`) or a backslash variant (`/\evil.example`, which browsers
 * normalise to `//`) would turn a return path into an open redirect.
 *
 * Both checks are load-bearing. The regex alone misses control characters: the
 * URL parser strips tab, LF and CR before parsing, so `/\t/evil.example`
 * resolves to `https://evil.example`. The origin check alone would accept a
 * relative path like `agents`, which resolves same-origin but against wherever
 * the visitor happens to stand.
 *
 * `origin` is a parameter rather than `window.location.origin` because one
 * caller is a route handler, where there is no window and the request carries
 * the origin instead.
 */
export function isSafeReturnPath(path: string | null | undefined, origin: string): path is string {
  return (
    typeof path === "string" && /^\/(?![/\\])/.test(path) && new URL(path, origin).origin === origin
  );
}
