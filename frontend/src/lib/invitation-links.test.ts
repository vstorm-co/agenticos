import { describe, expect, it } from "vitest";

import {
  invitationFlowFrom,
  invitationTokenFrom,
  isInvitationFlow,
  pendingLandingFor,
  registerHref,
  stageCookieName,
} from "./invitation-links";
import { ROUTES } from "./constants";

/**
 * Reading an invitation token off a deep link, and carrying its landing onward.
 *
 * An invitee with no account opens `/invitations/<token>`; `AuthGuard` exchanges the
 * token for an httpOnly handle (#1414) and bounces them to
 * `/login?returnTo=%2Finvitations%2Fpending`. `invitationTokenFrom` is what reads the
 * token off the path for that exchange; `registerHref` carries the credential-free
 * landing on to the sign-up form, so the invitee returns to close the invitation.
 */

describe("reading a token out of a path", () => {
  it("finds one on the path this app produces", () => {
    expect(invitationTokenFrom("/invitations/abc123")).toBe("abc123");
  });

  it("finds one behind a locale prefix", () => {
    // `localePrefix: "as-needed"`, so both shapes are real.
    expect(invitationTokenFrom("/pl/invitations/abc123")).toBe("abc123");
  });

  it("tolerates a trailing slash", () => {
    expect(invitationTokenFrom("/invitations/abc123/")).toBe("abc123");
  });

  it("answers nothing when there is nothing to read", () => {
    expect(invitationTokenFrom(null)).toBeNull();
    expect(invitationTokenFrom(undefined)).toBeNull();
    expect(invitationTokenFrom("")).toBeNull();
  });

  it("answers nothing for a path that is not an invitation", () => {
    expect(invitationTokenFrom("/agents")).toBeNull();
    expect(invitationTokenFrom("/invitations")).toBeNull();
  });

  it("does not read the credential-free pending landing as a token (#1414)", () => {
    // `/invitations/pending` matches the shape but names no invitation; reading it as
    // a token would stage the literal `pending` on a signed-out load of the landing.
    expect(invitationTokenFrom("/invitations/pending")).toBeNull();
    expect(invitationTokenFrom("/pl/invitations/pending")).toBeNull();
  });

  it("does not guess at a shape it was not given", () => {
    // A token is the only segment this reads; anything else is refused rather than
    // half-parsed into something that would be sent to the API as a token.
    expect(invitationTokenFrom("/invitations/abc/extra")).toBeNull();
    expect(invitationTokenFrom("/invitations/abc?x=1")).toBeNull();
    expect(invitationTokenFrom("https://evil.example/invitations/abc")).toBeNull();
    expect(invitationTokenFrom("/invitations/../../etc/passwd")).toBeNull();
  });
});

describe("the flow a staging is bound to", () => {
  const flow = "0123456789abcdef0123456789abcdef";

  it("is carried on the pending landing and names the cookie holding its handle", () => {
    expect(pendingLandingFor(flow)).toBe(`/invitations/pending?flow=${flow}`);
    expect(stageCookieName(flow)).toBe(`invitation_stage_${flow}`);
  });

  it("is read back off the landing, behind a locale prefix too", () => {
    expect(invitationFlowFrom(pendingLandingFor(flow))).toBe(flow);
    expect(invitationFlowFrom(`/pl/invitations/pending?flow=${flow}`)).toBe(flow);
    expect(invitationFlowFrom(`/invitations/pending/?flow=${flow}&registered=true`)).toBe(flow);
  });

  it("is only ever 32 hex digits, because a cookie name is built from it", () => {
    expect(isInvitationFlow(flow)).toBe(true);
    expect(isInvitationFlow("../access_token")).toBe(false);
    expect(isInvitationFlow(flow.toUpperCase())).toBe(false);
    expect(isInvitationFlow(flow.slice(1))).toBe(false);
    expect(isInvitationFlow(null)).toBe(false);
    expect(isInvitationFlow(undefined)).toBe(false);
  });

  it("is absent from anything that is not the landing for one", () => {
    expect(invitationFlowFrom(null)).toBeNull();
    expect(invitationFlowFrom("")).toBeNull();
    expect(invitationFlowFrom("/invitations/pending")).toBeNull();
    expect(invitationFlowFrom("/invitations/pending?flow=not-a-flow")).toBeNull();
    expect(invitationFlowFrom(`/agents?flow=${flow}`)).toBeNull();
    expect(invitationFlowFrom(`/invitations/${flow}`)).toBeNull();
    expect(invitationFlowFrom(`https://evil.example/invitations/pending?flow=${flow}`)).toBeNull();
    expect(invitationFlowFrom(`//evil.example/invitations/pending?flow=${flow}`)).toBeNull();
  });

  it("is not read as a token, so the landing is never staged", () => {
    expect(invitationTokenFrom(pendingLandingFor(flow))).toBeNull();
  });
});

describe("where create-an-account points", () => {
  it("is the plain register page when there is no landing to carry", () => {
    expect(registerHref("")).toBe(ROUTES.REGISTER);
  });

  it("carries the credential-free landing on, and nothing else", () => {
    // The token is gone by now - it was staged into a cookie - so the landing is
    // `/invitations/pending`, which registering must return to because it does not
    // accept the invitation itself (that needs a session).
    const href = registerHref("returnTo=%2Finvitations%2Fpending");
    const params = new URLSearchParams(href.split("?")[1]);

    expect(href.startsWith(ROUTES.REGISTER)).toBe(true);
    expect(params.get("returnTo")).toBe("/invitations/pending");
    expect(params.get("invitation")).toBeNull();
  });

  it("keeps a non-invitation returnTo too, rather than dropping it", () => {
    const params = new URLSearchParams(registerHref("returnTo=%2Fagents").split("?")[1]);

    expect(params.get("returnTo")).toBe("/agents");
  });

  it("takes only the returnTo out of a query carrying other parameters", () => {
    const params = new URLSearchParams(
      registerHref("registered=true&returnTo=%2Finvitations%2Fpending").split("?")[1],
    );

    expect(params.get("returnTo")).toBe("/invitations/pending");
    expect(params.get("registered")).toBeNull();
  });
});
