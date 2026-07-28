import type { MetadataRoute } from "next";

import { locales } from "@/i18n";
import { SITE } from "@/lib/seo";

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

  return {
    rules: [{ userAgent: "*", allow, disallow: ["/"] }],
    sitemap: `${SITE.url}/sitemap.xml`,
    host: SITE.url,
  };
}
