import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, CSP_DIRECTIVES } from "./csp";

/**
 * A policy is a list of quiet refusals, which is why it is worth a test.
 *
 * A missing directive breaks nothing that a build or a log would notice: the
 * page renders, one pane inside it is empty, and the reason is a line in one
 * visitor's browser console. `frame-src` was absent for exactly that long, and
 * every PDF and HTML preview in the product was blank (#1039).
 */
describe("the console's content security policy", () => {
  it("frames a blob, because that is what a document preview is", () => {
    // The viewer fetches the bytes, mints a blob URL and puts it in an iframe.
    // Without this the policy falls back to `default-src 'self'` and refuses it.
    expect(CSP_DIRECTIVES["frame-src"]).toContain("blob:");
    expect(contentSecurityPolicy).toContain("frame-src 'self' blob:");
  });

  it("does not frame a data URL", () => {
    // A document of somebody else's choosing, running as this origin. A blob URL
    // can only be minted by this origin's own script; a data URL is whatever was
    // in the markup.
    expect(CSP_DIRECTIVES["frame-src"]).not.toContain("data:");
  });

  it("lets nobody frame the console", () => {
    expect(CSP_DIRECTIVES["frame-ancestors"]).toEqual(["'none'"]);
  });

  it("keeps every fetch, socket and form on this origin", () => {
    expect(CSP_DIRECTIVES["default-src"]).toEqual(["'self'"]);
    expect(CSP_DIRECTIVES["form-action"]).toEqual(["'self'"]);
    expect(CSP_DIRECTIVES["base-uri"]).toEqual(["'self'"]);
    // Only `localhost` is named besides this origin, and only for a developer
    // whose backend is on another port.
    for (const source of CSP_DIRECTIVES["connect-src"]) {
      expect(source).toMatch(/^('self'|ws:|wss:|https?:\/\/localhost:\*)$/);
    }
  });

  it("names no wildcard host anywhere", () => {
    // `*` in any of these is the policy switched off for that resource type.
    for (const sources of Object.values(CSP_DIRECTIVES)) {
      expect(sources).not.toContain("*");
    }
  });

  it("is one line, in the order the directives are written", () => {
    expect(contentSecurityPolicy).not.toContain("\n");
    expect(contentSecurityPolicy.startsWith("default-src 'self';")).toBe(true);
  });
});
