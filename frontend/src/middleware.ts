import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";

import {
  LOCALE_COOKIE_MAX_AGE,
  LOCALE_COOKIE_NAME,
  localePrefixOf,
  pickedLocale,
  routing,
} from "./lib/locale-routing";
import { readPublicConfig } from "./lib/public-config";
import { contentSecurityPolicyHeader } from "./lib/security-headers";

const handleI18nRouting = createMiddleware(routing);

/**
 * Send a request whose URL carries no locale to the one the visitor picked.
 *
 * With `localePrefix: "as-needed"` the prefix is the whole of the locale: a path
 * without one resolves to `defaultLocale`. So an ordinary `<Link href="/agents">`
 * or `router.push("/orgs")` - and there are dozens, none of them locale-aware -
 * silently switched the UI back to English, which is what #285 saw as the choice
 * "reverting" on the next navigation.
 *
 * next-intl reads the cookie itself, but only under `localeDetection`, which also
 * turns on `accept-language` sniffing - and a Polish browser must still be served
 * English until somebody asks for Polish. So the cookie is read here and the header
 * is not.
 */
function restorePickedLocale(request: NextRequest): NextResponse | null {
  const { pathname } = request.nextUrl;
  if (localePrefixOf(pathname)) return null;

  const picked = pickedLocale(request.cookies.get(LOCALE_COOKIE_NAME)?.value);
  if (!picked) return null;

  const url = request.nextUrl.clone();
  url.pathname = `/${picked}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

/**
 * Record the locale a prefixed path names, so it outlives that path.
 *
 * next-intl writes the cookie itself only when the request carries none *and*
 * `accept-language` disagrees with the locale it resolved. So a Polish browser
 * opening a shared `/pl/agents` persists nothing, and its next ordinary `<Link>`
 * is English again - #285 arriving by URL rather than by the switcher, for the
 * visitors most likely to want Polish.
 *
 * Document requests only. A background request is how the router revalidates a
 * route of the locale the visitor has just left, so writing from one would undo
 * the switch they have just made; next-intl's `syncCookie` reads the same header
 * for the same reason.
 */
function rememberPrefixedLocale(request: NextRequest, response: NextResponse): void {
  if ((request.headers.get("sec-fetch-dest") ?? "document") !== "document") return;

  const named = localePrefixOf(request.nextUrl.pathname);
  if (!named || request.cookies.get(LOCALE_COOKIE_NAME)?.value === named) return;

  response.cookies.set(LOCALE_COOKIE_NAME, named, {
    path: "/",
    maxAge: LOCALE_COOKIE_MAX_AGE,
    sameSite: "lax",
  });
}

/**
 * A single-use, unguessable value for this request's `script-src 'nonce-…'`.
 *
 * 128 random bits, base64. Regenerated per request: a nonce reused across
 * responses is one an attacker can read from an earlier page and reuse, which is
 * `'unsafe-inline'` with extra steps (#1624).
 */
function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Stamp the Content-Security-Policy, which names this deployment's public origins
 * and this request's script nonce.
 *
 * Here and not in `next.config.ts`, whose `headers()` runs at build: `connect-src`
 * has to allow `PUBLIC_API_URL` and `PUBLIC_WS_URL`, read from the server's
 * environment on every request (#1544), and the nonce cannot be a build constant.
 * The rest of the security headers are constants and stay in the config.
 */
function withContentSecurityPolicy(response: NextResponse, csp: string): NextResponse {
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export default function middleware(request: NextRequest): NextResponse {
  const nonce = generateNonce();
  const { value: csp } = contentSecurityPolicyHeader(readPublicConfig(process.env), nonce);

  const restored = restorePickedLocale(request);
  if (restored) return withContentSecurityPolicy(restored, csp);

  // Next stamps the nonce onto its own inline flight scripts when it finds it on
  // the *request's* Content-Security-Policy header, so it has to be forwarded to
  // the render, not only set on the response. `x-nonce` rides along for a server
  // component that renders a <script> of its own. next-intl forwards the headers
  // of the request it is handed, so the render sees both.
  const forwardedHeaders = new Headers(request.headers);
  forwardedHeaders.set("x-nonce", nonce);
  forwardedHeaders.set("Content-Security-Policy", csp);
  const routedRequest = new NextRequest(request, { headers: forwardedHeaders });

  const response = handleI18nRouting(routedRequest);
  rememberPrefixedLocale(request, response);
  return withContentSecurityPolicy(response, csp);
}

export const config = {
  matcher: [
    // Match all pathnames except for:
    // - /api (API routes)
    // - /_next (Next.js internals)
    // - /static (inside /public)
    // - /_vercel (Vercel internals)
    // - All root files like favicon.ico, robots.txt, etc.
    // - App-router metadata convention routes (icon, apple-icon, opengraph-image,
    //   twitter-image, manifest.*, robots, sitemap) - these are dotless URLs
    //   that Next.js generates from src/app/{icon,apple-icon,…}.tsx and would
    //   otherwise be redirected to /{locale}/icon → 404.
    "/((?!api|_next|_vercel|static|icon$|apple-icon$|opengraph-image$|twitter-image$|manifest|robots$|sitemap$|.*\\..*).*)",
  ],
};
