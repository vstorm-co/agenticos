import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, cspDirectives } from "./csp";
import { DEFAULT_PUBLIC_CONFIG, type PublicConfig } from "./public-config";

/**
 * A policy is a list of quiet refusals, which is why it is worth a test.
 *
 * A missing directive breaks nothing that a build or a log would notice: the
 * page renders, one pane inside it is empty, and the reason is a line in one
 * visitor's browser console. `frame-src` was absent for exactly that long, and
 * every PDF and HTML preview in the product was blank (#1039).
 */
const SPLIT_ORIGIN: PublicConfig = {
  ...DEFAULT_PUBLIC_CONFIG,
  apiUrl: "https://api.acme.example",
  wsUrl: "wss://ws.acme.example",
};

describe("the console's content security policy", () => {
  const directives = cspDirectives(DEFAULT_PUBLIC_CONFIG);

  it("frames a blob, because that is what a document preview is", () => {
    // The viewer fetches the bytes, mints a blob URL and puts it in an iframe.
    // Without this the policy falls back to `default-src 'self'` and refuses it.
    expect(directives["frame-src"]).toContain("blob:");
    expect(contentSecurityPolicy(DEFAULT_PUBLIC_CONFIG)).toContain("frame-src 'self' blob:");
  });

  it("does not frame a data URL", () => {
    // A document of somebody else's choosing, running as this origin. A blob URL
    // can only be minted by this origin's own script; a data URL is whatever was
    // in the markup.
    expect(directives["frame-src"]).not.toContain("data:");
  });

  it("lets nobody frame the console", () => {
    expect(directives["frame-ancestors"]).toEqual(["'none'"]);
  });

  it("keeps every fetch and form on this origin", () => {
    expect(directives["default-src"]).toEqual(["'self'"]);
    expect(directives["form-action"]).toEqual(["'self'"]);
    expect(directives["base-uri"]).toEqual(["'self'"]);
  });

  it("lets the browser reach exactly the API and the socket the deployment named", () => {
    // The hosted chat uploads straight to `PUBLIC_API_URL` and the chat opens
    // `PUBLIC_WS_URL`; a policy that named `localhost` and a scheme-wide `wss:`
    // blocked the first on a split-origin deployment and let the second open to
    // any host (#1416 review).
    expect(cspDirectives(SPLIT_ORIGIN)["connect-src"]).toEqual([
      "'self'",
      "https://api.acme.example",
      "wss://ws.acme.example",
    ]);
  });

  it("names an origin, never a path, and names it once", () => {
    const withPaths: PublicConfig = {
      ...SPLIT_ORIGIN,
      apiUrl: "https://acme.example/api",
      wsUrl: "wss://acme.example/ws",
    };
    expect(cspDirectives(withPaths)["connect-src"]).toEqual([
      "'self'",
      "https://acme.example",
      "wss://acme.example",
    ]);
  });

  it("names no scheme-wide source and no wildcard host anywhere", () => {
    // `wss:` alone is every WebSocket server there is; `*` in any directive is
    // the policy switched off for that resource type.
    for (const sources of Object.values(cspDirectives(SPLIT_ORIGIN))) {
      expect(sources).not.toContain("*");
      for (const source of sources) expect(source).not.toMatch(/^wss?:$/);
    }
  });

  it("forbids plugin content outright", () => {
    // `<object>`/`<embed>` are not covered by `default-src` on their own, and the
    // console renders none (#1416).
    expect(directives["object-src"]).toEqual(["'none'"]);
    expect(contentSecurityPolicy(DEFAULT_PUBLIC_CONFIG)).toContain("object-src 'none'");
  });

  it("is one line, in the order the directives are written", () => {
    const policy = contentSecurityPolicy(DEFAULT_PUBLIC_CONFIG);
    expect(policy).not.toContain("\n");
    expect(policy.startsWith("default-src 'self';")).toBe(true);
  });
});
