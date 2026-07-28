import type { MetadataRoute } from "next";

import { SITE } from "@/lib/seo";

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
  path: string,
  changeFrequency: Freq,
  priority: number,
  lastModified: Date,
): MetadataRoute.Sitemap {
  const languages: Record<string, string> = Object.fromEntries(
    SITE.locales.map((l) => [l, `${SITE.url}/${l}${path}`]),
  );
  languages["x-default"] = `${SITE.url}/${SITE.defaultLocale}${path}`;

  return SITE.locales.map((locale) => ({
    url: `${SITE.url}/${locale}${path}`,
    lastModified,
    changeFrequency,
    priority,
    alternates: { languages },
  }));
}

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return PUBLIC_PATHS.flatMap(({ path, changeFrequency, priority }) =>
    entryFor(path, changeFrequency, priority, now),
  );
}
