import { describe, expect, it } from "vitest";

import { privacyLink, termsLink } from "./legal-links";
import { ROUTES } from "./constants";

/**
 * Whose terms a deployment links to.
 *
 * The built-in `/legal/*` pages describe *our* terms, which is wrong for a
 * deployment running under somebody else's name - so the interesting assertion here
 * is the `external` flag rather than the href: an operator's own policy is on
 * another origin, and opening it in the same tab from a half-filled sign-up form
 * loses what the visitor typed.
 */

describe("the terms link", () => {
  it("is the built-in page when the deployment has not named its own", () => {
    expect(termsLink({ termsUrl: null })).toEqual({
      href: ROUTES.LEGAL_TERMS,
      external: false,
    });
  });

  it("is the operator's own, in a new tab, once they name one", () => {
    expect(termsLink({ termsUrl: "https://acme.com/terms" })).toEqual({
      href: "https://acme.com/terms",
      external: true,
    });
  });
});

describe("the privacy link", () => {
  it("is the built-in page by default", () => {
    expect(privacyLink({ privacyUrl: null })).toEqual({
      href: ROUTES.LEGAL_PRIVACY,
      external: false,
    });
  });

  it("is the operator's own once they name one", () => {
    expect(privacyLink({ privacyUrl: "https://acme.com/privacy" })).toEqual({
      href: "https://acme.com/privacy",
      external: true,
    });
  });

  it("is decided independently of the terms link", () => {
    // An operator may have their own privacy policy and no separate terms page.
    expect(privacyLink({ privacyUrl: "https://acme.com/privacy" }).external).toBe(true);
    expect(termsLink({ termsUrl: null }).external).toBe(false);
  });
});
