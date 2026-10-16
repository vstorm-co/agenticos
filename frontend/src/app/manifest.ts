import type { MetadataRoute } from "next";

import { readBranding } from "@/lib/branding-server";
import { LOGO_VERSION } from "@/lib/logo.generated";
import { SITE } from "@/lib/seo";

/**
 * The installed-app identity: what a home-screen icon is captioned with.
 *
 * Reads the settings row, like the root layout's metadata does, because a
 * deployment somebody installed under its own name and finds captioned
 * `agenticos` has been renamed everywhere except the one place it is a shortcut.
 */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const { appName, description } = await readBranding();
  return {
    name: appName,
    short_name: appName,
    description,
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0E0E0C",
    theme_color: SITE.themeColor,
    categories: ["productivity", "business", "ai"],
    icons: [
      { src: `/icon?v=${LOGO_VERSION}`, sizes: "32x32", type: "image/png", purpose: "any" },
      {
        src: `/apple-icon?v=${LOGO_VERSION}`,
        sizes: "180x180",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
