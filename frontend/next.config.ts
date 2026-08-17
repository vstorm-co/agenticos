import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n.ts");

// Content Security Policy directives
const _frameAncestors = "frame-ancestors 'none';";

const ContentSecurityPolicy = `
  default-src 'self';
  script-src 'self' 'unsafe-eval' 'unsafe-inline';
  style-src 'self' 'unsafe-inline';
  img-src 'self' blob: data: https:;
  font-src 'self' data:;
  connect-src 'self' ws: wss: http://localhost:* https://localhost:*;
  ${_frameAncestors}
  base-uri 'self';
  form-action 'self';
`
  .replace(/\n/g, " ")
  .trim();

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: ContentSecurityPolicy,
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "X-XSS-Protection",
    value: "1; mode=block",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

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
  { from: "/settings/providers", to: "/vault" },
  { from: "/providers", to: "/vault" },
  { from: "/settings/mcp-servers", to: "/mcp-servers" },
  // The catalog and a person's own connections were two pages presented as
  // peers, which is why nobody could say what separated them. They are one page
  // now, with connection state on the row it belongs to.
  { from: "/settings/integrations", to: "/mcp-servers" },
  // The organization's integrations page rendered the same two components over
  // the same rows as `/kb/{id}`, and the only thing it could show that a
  // collection's page cannot is an integration assigned to no collection yet.
  // Those now live on `/kb`, next to the collections they get cloned into, so
  // the whole page goes rather than being kept for one section. `:id` is a
  // path parameter Next matches and then drops — every organization's old URL
  // lands on the same list, which is the one the active organization owns.
  { from: "/orgs/:id/integrations", to: "/kb" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  pageExtensions: ["ts", "tsx"],

  async redirects() {
    // `localePrefix: "as-needed"` means both `/settings/providers` and
    // `/pl/settings/providers` are URLs someone can hold, so both are matched.
    // These run before the next-intl middleware, which then normalises the
    // locale on the destination.
    return MOVED_ROUTES.flatMap(({ from, to }) => [
      { source: from, destination: to, permanent: false },
      { source: `/:locale(en|pl)${from}`, destination: `/:locale${to}`, permanent: false },
    ]);
  },

  // Security headers
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
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
