import type { Metadata, Viewport } from "next";
import { getLocale } from "next-intl/server";
import localFont from "next/font/local";
import "./globals.css";
import { SITE } from "@/lib/seo";

// Vendored, not `next/font/google`: that helper resolves a family against
// `fonts.gstatic.com` while `next build` runs, so a 404 from the CDN failed the
// build on branches that never touched the frontend (#572). `src/app/fonts/`
// says where each file came from and how to refresh it.
//
// Each family is two faces of one `font-family`: the latin file, and a
// latin-ext file gated by `unicode-range` so Polish diacritics render in the
// brand font while its bytes are fetched only when such a glyph appears (#606).
// The `font-family` each `*Ext` call declares is the name the bundler derives
// from its latin sibling's identifier - the family the emitted `--font-*`
// variables reference - so the ext face joins that family instead of getting
// one of its own that no stack names. Rename a const and its string must
// follow; the ranges are written out per call because the font transform
// refuses identifiers.
const display = localFont({
  src: "./fonts/bricolage-grotesque-latin.woff2",
  variable: "--font-display",
  weight: "700 800",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    },
  ],
});

const displayExt = localFont({
  src: "./fonts/bricolage-grotesque-latin-ext.woff2",
  variable: "--font-display-ext",
  weight: "700 800",
  display: "swap",
  preload: false,
  adjustFontFallback: false,
  declarations: [
    { prop: "font-family", value: "display" },
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    },
  ],
});

const body = localFont({
  src: "./fonts/inter-latin.woff2",
  variable: "--font-body",
  weight: "400 700",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    },
  ],
});

const bodyExt = localFont({
  src: "./fonts/inter-latin-ext.woff2",
  variable: "--font-body-ext",
  weight: "400 700",
  display: "swap",
  preload: false,
  adjustFontFallback: false,
  declarations: [
    { prop: "font-family", value: "body" },
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    },
  ],
});

const mono = localFont({
  src: "./fonts/geist-mono-latin.woff2",
  variable: "--font-mono",
  weight: "400 500",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    },
  ],
});

const monoExt = localFont({
  src: "./fonts/geist-mono-latin-ext.woff2",
  variable: "--font-mono-ext",
  weight: "400 500",
  display: "swap",
  preload: false,
  adjustFontFallback: false,
  declarations: [
    { prop: "font-family", value: "mono" },
    {
      prop: "unicode-range",
      value:
        // i18n-exempt: a CSS unicode-range value, not copy.
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
    },
  ],
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE.url),
  title: {
    default: `${SITE.name} - ${SITE.tagline}`,
    template: `%s | ${SITE.name}`,
  },
  description: SITE.description,
  applicationName: SITE.name,
  keywords: [...SITE.keywords],
  authors: [{ name: SITE.name }],
  creator: SITE.name,
  publisher: SITE.name,
  formatDetection: { email: false, address: false, telephone: false },
  // Default OG; per-page generateMetadata can override.
  openGraph: {
    type: "website",
    siteName: SITE.name,
    title: `${SITE.name} - ${SITE.tagline}`,
    description: SITE.description,
    url: SITE.url,
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: SITE.name }],
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE.name} - ${SITE.tagline}`,
    description: SITE.description,
    images: ["/opengraph-image"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  },
  icons: {
    // /icon.tsx + /apple-icon.tsx render PNGs via next/og - declare them as PNG
    // so browsers don't reject the response on a Content-Type mismatch.
    icon: [{ url: "/icon", sizes: "32x32", type: "image/png" }],
    apple: [{ url: "/apple-icon", sizes: "180x180", type: "image/png" }],
  },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  // Required for env(safe-area-inset-*) to evaluate non-zero on iOS notches -
  // used by the mobile bottom tab bar.
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F5F2E8" },
    { media: "(prefers-color-scheme: dark)", color: SITE.themeColor },
  ],
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();

  return (
    <html
      lang={locale}
      suppressHydrationWarning
      className={`${display.variable} ${displayExt.variable} ${body.variable} ${bodyExt.variable} ${mono.variable} ${monoExt.variable}`}
    >
      <body className="font-body">{children}</body>
    </html>
  );
}
