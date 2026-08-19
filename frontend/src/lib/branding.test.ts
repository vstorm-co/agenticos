import { describe, expect, it } from "vitest";

import {
  BUILT_IN_BRANDING,
  brandingImageUrl,
  resolveBranding,
  type BrandingResponse,
} from "./branding";
import { APP_NAME } from "./constants";
import { SITE } from "./seo";

/**
 * Folding the administrator's overrides onto what this build ships with.
 *
 * The API answers overrides and nothing else, so the resolution has to happen
 * somewhere - and it happens here rather than on the server so there is one default
 * per renderer instead of an effective value plus a fallback copy of the same
 * constant. What that buys is only real if a null actually falls through, which is
 * most of what is asserted below.
 */

function response(overrides: Partial<BrandingResponse> = {}): BrandingResponse {
  return {
    app_name: null,
    tagline: null,
    description: null,
    logo_version: null,
    favicon_version: null,
    footer_text: null,
    terms_url: null,
    privacy_url: null,
    signup_mode: "open",
    allowed_email_domains: [],
    maintenance_mode: false,
    maintenance_message: null,
    ...overrides,
  };
}

describe("the built-in identity", () => {
  it("is what this build ships with, from the constants that already held it", () => {
    expect(BUILT_IN_BRANDING.appName).toBe(APP_NAME);
    expect(BUILT_IN_BRANDING.tagline).toBe(SITE.tagline);
    expect(BUILT_IN_BRANDING.description).toBe(SITE.description);
  });

  it("ships open, with no mark and no policy of its own", () => {
    expect(BUILT_IN_BRANDING.signupMode).toBe("open");
    expect(BUILT_IN_BRANDING.allowedEmailDomains).toEqual([]);
    expect(BUILT_IN_BRANDING.logoUrl).toBeNull();
    expect(BUILT_IN_BRANDING.maintenanceMode).toBe(false);
  });
});

describe("resolving what the administrator overrode", () => {
  it("answers the built-in when there is nothing to fold", () => {
    expect(resolveBranding(null)).toEqual(BUILT_IN_BRANDING);
    expect(resolveBranding(undefined)).toEqual(BUILT_IN_BRANDING);
  });

  it("keeps every override that was actually set", () => {
    const branding = resolveBranding(
      response({
        app_name: "Acme AI",
        tagline: "Agents for Acme",
        description: "Ours.",
        footer_text: "© Acme",
        terms_url: "https://acme.com/terms",
        privacy_url: "https://acme.com/privacy",
        signup_mode: "invite_only",
        allowed_email_domains: ["acme.com"],
        maintenance_mode: true,
        maintenance_message: "Back at 22:00",
      }),
    );

    expect(branding).toEqual({
      appName: "Acme AI",
      tagline: "Agents for Acme",
      description: "Ours.",
      logoUrl: null,
      faviconUrl: null,
      footerText: "© Acme",
      termsUrl: "https://acme.com/terms",
      privacyUrl: "https://acme.com/privacy",
      signupMode: "invite_only",
      allowedEmailDomains: ["acme.com"],
      maintenanceMode: true,
      maintenanceMessage: "Back at 22:00",
    });
  });

  it("falls through to the built-in for a field nobody set", () => {
    const branding = resolveBranding(response({ app_name: "Acme AI" }));

    expect(branding.appName).toBe("Acme AI");
    expect(branding.tagline).toBe(BUILT_IN_BRANDING.tagline);
    expect(branding.description).toBe(BUILT_IN_BRANDING.description);
  });

  it("treats an empty string as absent", () => {
    // The backend already turns a cleared input into null. This is the second
    // guard, because a name that renders as nothing on a sign-in page is worse
    // than one that is merely not theirs.
    const branding = resolveBranding(response({ app_name: "", tagline: "" }));

    expect(branding.appName).toBe(BUILT_IN_BRANDING.appName);
    expect(branding.tagline).toBe(BUILT_IN_BRANDING.tagline);
  });

  it("has no built-in for the fields that have none", () => {
    // A footer, an external terms link and a maintenance message are absent by
    // default - there is nothing to fall back to, and inventing one would put a
    // sentence on screen nobody wrote.
    const branding = resolveBranding(response({ footer_text: "", maintenance_message: "" }));

    expect(branding.footerText).toBeNull();
    expect(branding.termsUrl).toBeNull();
    expect(branding.maintenanceMessage).toBeNull();
  });

  it("turns a stored image's version into an address this app serves", () => {
    const branding = resolveBranding(response({ logo_version: 42, favicon_version: 43 }));

    expect(branding.logoUrl).toBe("/api/branding/mark/logo?v=42");
    expect(branding.faviconUrl).toBe("/api/branding/mark/favicon?v=43");
  });
});

describe("where a branding image is fetched from", () => {
  it("is null when no image is stored", () => {
    expect(brandingImageUrl("logo", null)).toBeNull();
    expect(brandingImageUrl("favicon", null)).toBeNull();
  });

  it("goes through this app rather than the API's own origin", () => {
    // In any deployment worth the name the API is not on this origin and may not
    // be reachable from a browser at all.
    expect(brandingImageUrl("logo", 1)).toBe("/api/branding/mark/logo?v=1");
  });

  it("carries the version, which is the only reason a replacement appears", () => {
    // The path is constant and the bytes are served `immutable` for a year.
    expect(brandingImageUrl("logo", 1)).not.toBe(brandingImageUrl("logo", 2));
  });

  it("keeps a zero version, which is a stamp and not an absence", () => {
    expect(brandingImageUrl("favicon", 0)).toBe("/api/branding/mark/favicon?v=0");
  });
});
