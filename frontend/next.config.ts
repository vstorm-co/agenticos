import { randomUUID } from "node:crypto";
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// A relative import, not `@/lib/...`: the path alias is resolved for the
// application's own build and this file is read before it. The headers live
// there so each can be asserted - one that goes missing breaks a pane in
// somebody's browser and nothing else (#1039, #1416). Only the static ones are
// set here: `headers()` runs at build, and the Content-Security-Policy names
// the deployment's public origins, which exist at runtime, so
// `src/middleware.ts` stamps that one.
import { staticSecurityHeaders } from "./src/lib/security-headers";
// The same relative-import bargain, and for a sharper reason: written out, the
// list went stale the moment a third locale shipped and German bookmarks 404'd.
import { locales } from "./src/lib/locales";

const withNextIntl = createNextIntlPlugin("./src/i18n.ts");

// Freeze one identity into the browser and version endpoint, even when the
// package version is unchanged. Inherit it when Next reloads this config in a
// build worker; all replicas should run the same built image.
const appBuildId = process.env.NEXT_PUBLIC_APP_BUILD_ID || randomUUID();
process.env.NEXT_PUBLIC_APP_BUILD_ID = appBuildId;

/**
 * Pages that have moved, and the URL that still has to work.
 *
 * `/settings/` is personal configuration — your profile, your account, your
 * notifications, your MCP connections. AI providers and the MCP catalog are the
 * organization's, they are primary entries in the sidebar rather than settings
 * tabs, and both are gated on an organization permission while nothing under
 * `/settings/` is gated at all. They now sit where they are navigated from.
 *
 * A bookmark or an in-flight link to the old URL still has to work, so each one
 * redirects. They are temporary (307) rather than permanent: a 308 is cached by
 * the browser indefinitely and cannot be taken back from the server, which is
 * not a bet worth making on an internal route in a product still moving its
 * navigation around.
 */
const MOVED_ROUTES: readonly { from: string; to: string }[] = [
  // Provider keys were never the whole of it: the same page holds the secrets a
  // capability is bound to, and a URL naming only half of what it shows is a URL
  // that has to be re-learned later. Both old spellings land on the vault, so
  // neither the pre-move bookmark nor the post-move one breaks.
  { from: "/settings/providers", to: "/connectors/vault" },
  { from: "/providers", to: "/connectors/vault" },
  { from: "/settings/mcp-servers", to: "/connectors" },
  // The catalog and a person's own connections were two pages presented as
  // peers, which is why nobody could say what separated them. They are one page
  // now, with connection state on the row it belongs to. That page is the Apps
  // tab of Connectors, which also holds the channels, remote agents, vault and
  // sandboxes that used to sit as their own nav entries.
  { from: "/mcp-servers", to: "/connectors" },
  { from: "/channels", to: "/connectors/channels" },
  { from: "/remote-agents", to: "/connectors/remote-agents" },
  { from: "/vault", to: "/connectors/vault" },
  { from: "/sandboxes", to: "/connectors/sandboxes" },
  { from: "/settings/integrations", to: "/connectors" },
  // The organization's integrations page rendered the same two components over
  // the same rows as `/kb/{id}`, and the only thing it could show that a
  // collection's page cannot is an integration assigned to no collection yet.
  // Those now live on `/kb`, next to the collections they get cloned into, so
  // the whole page goes rather than being kept for one section. `:id` is a
  // path parameter Next matches and then drops — every organization's old URL
  // lands on the same list, which is the one the active organization owns.
  { from: "/orgs/:id/integrations", to: "/kb" },
  // Apps were called artifacts until #2071, and a link to one sits in emails,
  // notifications and old conversations.
  { from: "/artifacts", to: "/apps" },
  { from: "/artifacts/:id", to: "/apps/:id" },
  // The files agents keep were "Agent files" at `/workspaces` until #2126; people
  // looked for them as documents, and a workspace meant something else to them.
  { from: "/workspaces", to: "/documents" },
  { from: "/workspaces/:id", to: "/documents/:id" },
];

export const nextConfig: NextConfig = {
  output: "standalone",
  generateBuildId: () => appBuildId,
  allowedDevOrigins: process.env.PUBLIC_SITE_URL
    ? [new URL(process.env.PUBLIC_SITE_URL).hostname]
    : undefined,
  // next-intl owns locale rewrites; Next must preserve their internal paths.
  skipProxyUrlNormalize: true,
  pageExtensions: ["ts", "tsx"],
  // The development badge sits in the corner the console's own controls use.
  devIndicators: false,
  // The widget's face route reads the generator's motion stylesheet from disk,
  // which nothing imports - so the standalone build would leave it behind.
  outputFileTracingIncludes: {
    "/api/public/face": ["./node_modules/blobatar/dist/motion.css"],
  },

  async redirects() {
    // `localePrefix: "as-needed"` means both `/settings/providers` and
    // `/pl/settings/providers` are URLs someone can hold, so both are matched.
    // These run before the next-intl middleware, which then normalises the
    // locale on the destination.
    return MOVED_ROUTES.flatMap(({ from, to }) => [
      { source: from, destination: to, permanent: false },
      {
        source: `/:locale(${locales.join("|")})${from}`,
        destination: `/:locale${to}`,
        permanent: false,
      },
    ]);
  },

  // Security headers
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [...staticSecurityHeaders],
      },
      // Webmail renders email HTML on another origin, and browsers require
      // CORS on font responses even when the email itself is publicly viewable.
      // Keep the wildcard limited to the public font files used by email.
      {
        source: "/fonts/email/:path*",
        headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
      },
      // Relax framing for the file endpoint so the chat preview panel can
      // embed PDFs/HTML in an iframe from the same origin. Listed AFTER the
      // catch-all so its values win for matching headers.
      {
        source: "/api/files/:path*",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
        ],
      },
    ];
  },
};
export default withNextIntl(nextConfig);
