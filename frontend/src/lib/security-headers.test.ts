import { describe, expect, it } from "vitest";

import { contentSecurityPolicy } from "./csp";
import { DEFAULT_PUBLIC_CONFIG } from "./public-config";
import { contentSecurityPolicyHeader, staticSecurityHeaders } from "./security-headers";

/**
 * Each header is asserted for the same reason the CSP is: one that goes missing
 * fails no build and appears in no log the deployment reads (#1039, #1416).
 */
describe("the console's security headers", () => {
  const every = [...staticSecurityHeaders, contentSecurityPolicyHeader(DEFAULT_PUBLIC_CONFIG)];
  const byKey = new Map(every.map((header) => [header.key, header.value]));

  it("carries every header a review expects, once each, between its two emitters", () => {
    expect([...byKey.keys()].sort()).toEqual([
      "Content-Security-Policy",
      "Permissions-Policy",
      "Referrer-Policy",
      "X-Content-Type-Options",
      "X-Frame-Options",
      "X-XSS-Protection",
    ]);
    // No key appears twice - a duplicate would let a proxy pick either value. The
    // static set is Next's at build; the policy is the middleware's per request.
    expect(every).toHaveLength(byKey.size);
    expect(staticSecurityHeaders.map((header) => header.key)).not.toContain(
      "Content-Security-Policy",
    );
  });

  it("sets the content security policy the CSP module builds for the deployment", () => {
    expect(byKey.get("Content-Security-Policy")).toBe(contentSecurityPolicy(DEFAULT_PUBLIC_CONFIG));
  });

  it("denies framing and sniffing, and leaks no path across origins", () => {
    expect(byKey.get("X-Frame-Options")).toBe("DENY");
    expect(byKey.get("X-Content-Type-Options")).toBe("nosniff");
    expect(byKey.get("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
    // The deprecated auditor is off, not blocking, so the CSP is the one policy.
    expect(byKey.get("X-XSS-Protection")).toBe("0");
  });

  it("denies camera and geolocation but lets speech-to-text use the microphone", () => {
    // The dictation button is the Web Speech API, which the `microphone` policy
    // gates; denying it outright would kill the feature silently (#1416).
    expect(byKey.get("Permissions-Policy")).toBe("camera=(), microphone=(self), geolocation=()");
  });
});
