import { describe, expect, it } from "vitest";

import { invitationTokenFrom, registerHref } from "./invitation-links";
import { ROUTES } from "./constants";

/**
 * Carrying an invitation across the redirect that used to lose it.
 *
 * An invitee with no account opens `/invitations/<token>`, `AuthGuard` bounces them to
 * `/login?returnTo=%2Finvitations%2F<token>`, and the only route onward was a plain
 * link to `/register` - which on an `invite_only` deployment then refused somebody
 * holding a valid invitation, because the request carried no token and no query over
 * their address can recognise a link that constrains no address (#916).
 */

describe("reading a token out of a returnTo", () => {
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

  it("does not guess at a shape it was not given", () => {
    // A token is the only segment this reads; anything else is refused rather than
    // half-parsed into something that would be sent to the API as a token.
    expect(invitationTokenFrom("/invitations/abc/extra")).toBeNull();
    expect(invitationTokenFrom("/invitations/abc?x=1")).toBeNull();
    expect(invitationTokenFrom("https://evil.example/invitations/abc")).toBeNull();
    expect(invitationTokenFrom("/invitations/../../etc/passwd")).toBeNull();
  });
});

describe("where create-an-account points", () => {
  it("is the plain register page when no invitation is in play", () => {
    expect(registerHref("")).toBe(ROUTES.REGISTER);
    expect(registerHref("returnTo=%2Fagents")).toBe(ROUTES.REGISTER);
  });

  it("carries the invitation when the login page was reached from one", () => {
    const href = registerHref("returnTo=%2Finvitations%2Fabc123");
    const params = new URLSearchParams(href.split("?")[1]);

    expect(href.startsWith(ROUTES.REGISTER)).toBe(true);
    expect(params.get("invitation")).toBe("abc123");
  });

  it("keeps the returnTo as well as the token", () => {
    // Registering does not accept the invitation - that needs a session - so the
    // person still has to land back on the invitation page afterwards.
    const params = new URLSearchParams(
      registerHref("returnTo=%2Finvitations%2Fabc123").split("?")[1],
    );

    expect(params.get("returnTo")).toBe("/invitations/abc123");
  });

  it("survives a query carrying other parameters", () => {
    const params = new URLSearchParams(
      registerHref("registered=true&returnTo=%2Finvitations%2Fabc123").split("?")[1],
    );

    expect(params.get("invitation")).toBe("abc123");
  });
});
