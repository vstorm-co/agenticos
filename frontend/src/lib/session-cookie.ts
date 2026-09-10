import type { NextRequest } from "next/server";

/**
 * Whether a session cookie set in answer to this request may carry `Secure`.
 *
 * `NODE_ENV === "production"` used to decide it, which made a production build
 * served over plain HTTP - `make dev-frontend`, opened at `http://localhost:3000`
 * - set cookies WebKit then discards: Safari, and every WKWebView including the
 * desktop shell's, does not extend to the `Secure` attribute the localhost
 * exception Chrome and Firefox make. The login answered 200 and every request
 * after it was "Not authenticated", with nothing in any log.
 *
 * The scheme the visitor is on is the question. Behind the bundled proxy the
 * request arrives over HTTP with `X-Forwarded-Proto: https`, so that header wins
 * when present, first hop first.
 */
export function secureCookies(request: NextRequest): boolean {
  const forwarded = request.headers.get("x-forwarded-proto");
  const scheme =
    forwarded === null
      ? request.nextUrl.protocol.slice(0, -1)
      : forwarded.replace(/,.*$/, "").trim();
  return scheme === "https";
}
