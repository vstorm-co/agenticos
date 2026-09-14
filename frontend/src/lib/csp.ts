/**
 * The Content Security Policy every page of the console is served with.
 *
 * Here rather than inline in `next.config.ts` so it can be asserted. A policy is
 * a list of quiet refusals: when a directive is missing, nothing fails to build
 * and nothing appears in a log the deployment reads - a pane renders empty and
 * the reason is in one visitor's browser console. `frame-src` was missing, so
 * every PDF and HTML preview in the product was blank while images worked
 * (#1039), and the only thing that would have caught it is a test naming the
 * directives.
 *
 * A function of the deployment's public origins rather than a constant: the API
 * and the chat WebSocket are `PUBLIC_API_URL` and `PUBLIC_WS_URL`, read from the
 * server's environment on every request since #1544, and `connect-src` has to
 * name exactly those. A build-time constant could only name `localhost` and a
 * scheme-wide `ws:`, which on a split-origin deployment blocks the hosted chat's
 * upload to the API and lets the socket open anywhere (#1416 review).
 */

import type { PublicConfig } from "./public-config";

/**
 * Every directive the header carries. A closed union rather than `string`, so a
 * lookup is a value and not a maybe - and so adding one is a decision made here
 * rather than a key appearing in an object literal.
 */
export type CspDirective =
  | "default-src"
  | "script-src"
  | "style-src"
  | "img-src"
  | "frame-src"
  | "font-src"
  | "connect-src"
  | "frame-ancestors"
  | "base-uri"
  | "form-action"
  | "object-src";

/** The origin a public URL names, so `connect-src` lists a host and not a path. */
function originOf(url: string): string {
  return new URL(url).origin;
}

/** What each directive allows for a deployment, in the order the header is written. */
export function cspDirectives(
  config: PublicConfig,
): Readonly<Record<CspDirective, readonly string[]>> {
  return {
    "default-src": ["'self'"],
    // `unsafe-eval` and `unsafe-inline`: Next's own runtime needs both in
    // development, and the app router inlines flight data in production.
    "script-src": ["'self'", "'unsafe-eval'", "'unsafe-inline'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    // `blob:` for a canvas export and for bytes fetched then handed to an `img`;
    // `https:` because a model provider's avatar and a connector's brand mark are
    // remote.
    "img-src": ["'self'", "blob:", "data:", "https:"],
    // A document the viewer cannot render itself - a PDF, an HTML page - goes in
    // an iframe whose `src` is a blob URL minted from bytes this origin already
    // fetched. Deliberately not `data:`: a data URL in a frame is a document of
    // somebody else's choosing running as this origin, which is the attack
    // `frame-src` exists to refuse. A blob URL can only be minted by this
    // origin's own script.
    "frame-src": ["'self'", "blob:"],
    "font-src": ["'self'", "data:"],
    // This origin's own BFF routes, the API the browser calls directly - OAuth,
    // the hosted chat's uploads - and the chat's WebSocket. Named from the
    // deployment's configuration, not a scheme: `wss:` alone would let the socket
    // open to any host.
    "connect-src": [...new Set(["'self'", originOf(config.apiUrl), originOf(config.wsUrl)])],
    // Nothing may frame the console. The embed widget is served from its own
    // route, which sets its own header.
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    // No `<object>`, `<embed>` or `<applet>` at all - the console renders none, and
    // they are a plugin-content vector `default-src` does not cover on its own.
    "object-src": ["'none'"],
  };
}

/** The header value for a deployment, as one line. */
export function contentSecurityPolicy(config: PublicConfig): string {
  return Object.entries(cspDirectives(config))
    .map(([directive, sources]) => `${directive} ${sources.join(" ")}`)
    .join("; ");
}
