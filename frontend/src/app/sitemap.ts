import type { MetadataRoute } from "next";

import { SITE, siteOrigin } from "@/lib/seo";

// Rendered per request, not prerendered at build: the origin is a runtime setting (#1544).
export const dynamic = "force-dynamic";

/** AgenticOS is self-hosted and has no public marketing surface. The only
 *  pages worth listing are the ones a signed-out visitor can legitimately
 *  reach: the legal documents and the two auth entry points. Everything else
 *  is authenticated and blocked in robots.ts. */
type Freq = MetadataRoute.Sitemap[number]["changeFrequency"];

const PUBLIC_PATHS: { path: string; changeFrequency: Freq; priority: number }[] = [
  { path: "/legal/terms", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/privacy", changeFrequency: "yearly", priority: 0.3 },
  { path: "/legal/cookies", changeFrequency: "yearly", priority: 0.3 },
  { path: "/login", changeFrequency: "yearly", priority: 0.3 },
  { path: "/register", changeFrequency: "yearly", priority: 0.5 },
];

function entryFor(
  origin: string,
  path: string,
  changeFrequency: Freq,
  priority: number,
  lastModified: Date,
): MetadataRoute.Sitemap {
  const languages: Record<string, string> = Object.fromEntries(
    SITE.locales.map((l) => [l, `${origin}/${l}${path}`]),
  );
  languages["x-default"] = `${origin}/${SITE.defaultLocale}${path}`;

  return SITE.locales.map((locale) => ({
    url: `${origin}/${locale}${path}`,
    lastModified,
    changeFrequency,
    priority,
    alternates: { languages },
  }));
}

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = siteOrigin();
  const now = new Date();
  return PUBLIC_PATHS.flatMap(({ path, changeFrequency, priority }) =>
    entryFor(origin, path, changeFrequency, priority, now),
  );
}
