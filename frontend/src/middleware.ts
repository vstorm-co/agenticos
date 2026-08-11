import createMiddleware from "next-intl/middleware";
import { NextResponse, type NextRequest } from "next/server";

import { locales, defaultLocale } from "./i18n";
import { LOCALE_COOKIE_NAME, localePrefixOf, routing } from "./lib/locale-routing";

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

  const picked = request.cookies.get(LOCALE_COOKIE_NAME)?.value;
  if (!picked || picked === defaultLocale || !(locales as readonly string[]).includes(picked)) {
    return null;
  }

  const url = request.nextUrl.clone();
  url.pathname = `/${picked}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

export default function middleware(request: NextRequest): NextResponse {
  return restorePickedLocale(request) ?? handleI18nRouting(request);
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
