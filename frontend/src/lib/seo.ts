/** Single source of truth for SEO metadata.
 *
 *  All public-page metadata helpers (root layout, per-page generateMetadata,
 *  sitemap, robots, manifest, OG image generator) pull from here. Edit one
 *  file to retheme the site's identity.
 *
 *  ENV: NEXT_PUBLIC_SITE_URL = canonical https origin (no trailing slash).
 *  Falls back to a sensible localhost default in dev.
 */

import type { Metadata } from "next";

import { APP_NAME } from "@/lib/constants";
import { defaultLocale, locales } from "@/i18n";

export const SITE = {
  name: APP_NAME,
  /**
   * Tagline used in title templates + OG defaults.
   *
   * Read by the root layout and the OG image route, both of which sit above the
   * `[locale]` segment and so have no locale to translate against.
   */
  // i18n-exempt: see above.
  tagline: "The operating system for your company's AI agents",
  /** One-paragraph default description (≤160 chars for SERP truncation). */
  description:
    // i18n-exempt: the tagline's reason, one line up - metadata read above `[locale]`.
    "Self-hosted, open source, and yours: agents are configuration you own, running on your infrastructure, against your keys.",
  /** Canonical absolute origin. NO trailing slash. */
  url:
    (process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") as string | undefined) ??
    "http://localhost:3000",
  /** Twitter handle for `twitter:site` (with @). Empty string disables. */
  twitter: "",
  /** Theme color used in PWA manifest + browser chrome. */
  themeColor: "#0E0E0C",
  /** Long-form keywords. Light SEO weight today; useful for clarity. */
  keywords: [
    "AI agents",
    "self-hosted",
    "open source",
    "agent platform",
    "RAG",
    "knowledge base",
    "multi-tenant",
    "audit trail",
  ],
  /** Locale defaults - pulls from your i18n config. */
  defaultLocale,
  locales: [...locales],
} as const;

/** Map our locale codes → BCP-47 / Open Graph locale strings. */
export const OG_LOCALE: Record<(typeof locales)[number], string> = {
  en: "en_US",
  pl: "pl_PL",
};

interface PageMetaInput {
  /** Page-specific title fragment. The template adds " | <brand>". */
  title: string;
  description: string;
  /** Path WITHOUT locale prefix (e.g. "/legal/terms"). Used to build canonical + alternates. */
  path?: string;
  /** Active locale. Defaults to site default. */
  locale?: (typeof locales)[number];
  /** Disable indexing (e.g. drafts, internal pages). */
  noindex?: boolean;
  /** Override OG image. Defaults to dynamic /opengraph-image. */
  ogImage?: string;
  /**
   * What this deployment calls itself, for the titles no template touches.
   *
   * Defaults to the built-in. A caller that has read the settings row - every
   * `generateMetadata` in the app - passes the effective name, so a renamed
   * deployment is not still `agenticos` on a shared link.
   */
  brand?: string;
}

/** Build a fully-formed Next.js Metadata object for a public page. */
export function pageMetadata(input: PageMetaInput): Metadata {
  const locale = input.locale ?? SITE.defaultLocale;
  const path = normalizePath(input.path ?? "/");
  const localizedPath = path === "/" ? `/${locale}` : `/${locale}${path}`;
  const canonical = `${SITE.url}${localizedPath}`;
  const brand = input.brand ?? SITE.name;
  // Bare, because the root layout's `title.template` is `%s | <brand>` and Next
  // applies it to whatever a page returns. Appending the brand here as well is how
  // every page title read `Sign in | agenticos | Acme AI` - the template's half
  // current, this half frozen at build time. A page whose title *is* the brand
  // opts out of the template rather than saying it twice.
  const title = input.title === brand ? { absolute: brand } : input.title;
  // OG and Twitter titles go through no template, so they carry the brand here.
  const socialTitle = input.title === brand ? brand : `${input.title} | ${brand}`;
  const ogImageUrl = input.ogImage ?? `${SITE.url}/opengraph-image`;

  return {
    title,
    description: input.description,
    keywords: [...SITE.keywords],
    alternates: {
      canonical,
      languages: Object.fromEntries(
        SITE.locales.map((loc) => [
          loc,
          `${SITE.url}${path === "/" ? `/${loc}` : `/${loc}${path}`}`,
        ]),
      ),
    },
    openGraph: {
      title: socialTitle,
      description: input.description,
      url: canonical,
      siteName: brand,
      type: "website",
      locale: OG_LOCALE[locale],
      alternateLocale: SITE.locales.filter((l) => l !== locale).map((l) => OG_LOCALE[l]),
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${brand} - ${SITE.tagline}`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: socialTitle,
      description: input.description,
      images: [ogImageUrl],
      ...(SITE.twitter ? { site: SITE.twitter, creator: SITE.twitter } : {}),
    },
    robots: input.noindex
      ? { index: false, follow: false }
      : { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  };
}

function normalizePath(p: string): string {
  if (!p.startsWith("/")) return `/${p}`;
  if (p.length > 1 && p.endsWith("/")) return p.slice(0, -1);
  return p;
}
