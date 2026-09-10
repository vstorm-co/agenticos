import type { MetadataRoute } from "next";

import { locales } from "@/i18n";
import { siteOrigin } from "@/lib/seo";

// Rendered per request, not prerendered at build: the origin is a runtime setting (#1544).
export const dynamic = "force-dynamic";

/** Robots policy.
 *
 *  A self-hosted AgenticOS deployment has no public marketing surface, so the
 *  rule is an allowlist rather than a blocklist: everything is disallowed and
 *  only the pages a signed-out visitor can legitimately reach are opened up.
 *  A blocklist would silently expose every route added later.
 *
 *  Paths are listed twice - bare and locale-prefixed - because `next-intl`
 *  serves the default locale unprefixed (`/login`) and the others prefixed
 *  (`/pl/login`), and robots.txt has no notion of an optional segment. */
const PUBLIC_PATHS = ["/login", "/register", "/legal/"];

export default function robots(): MetadataRoute.Robots {
  const allow = PUBLIC_PATHS.flatMap((path) => [
    path,
    ...locales.map((locale) => `/${locale}${path}`),
  ]);

  const origin = siteOrigin();
  return {
    rules: [{ userAgent: "*", allow, disallow: ["/"] }],
    sitemap: `${origin}/sitemap.xml`,
    host: origin,
  };
}
