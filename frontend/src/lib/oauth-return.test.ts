import { afterEach, describe, expect, it, vi } from "vitest";

import { rememberReturnTo, returnToForAttempt, takeReturnTo } from "./oauth-return";

afterEach(() => {
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});

/**
 * The deep link's ride across the provider round trip (#135).
 *
 * A visitor at `/login?returnTo=/agents/a-1` who signs in with the password form
 * resumes the deep link; one who clicked a provider button landed on the
 * dashboard, so which button they picked decided where they ended up.
 */
describe("carrying a return path across the provider round trip", () => {
  it("hands back what was remembered", () => {
    rememberReturnTo("/agents/a-1");

    expect(takeReturnTo()).toBe("/agents/a-1");
  });

  it("consumes it, so an abandoned deep link is not resumed later", () => {
    rememberReturnTo("/agents/a-1");
    takeReturnTo();

    expect(takeReturnTo()).toBeNull();
  });

  it("forgets an earlier path when there is nothing to remember", () => {
    // A visitor who arrives at /login with a deep link, gives up, and comes
    // back plainly should land on the dashboard rather than where they were
    // going the first time.
    rememberReturnTo("/agents/a-1");
    rememberReturnTo(null);

    expect(takeReturnTo()).toBeNull();
  });

  it("answers with nothing where the trip did not start", () => {
    expect(takeReturnTo()).toBeNull();
  });

  it("still lets a browser that refuses site data sign in", () => {
    // The cost of a throwing accessor is landing on the dashboard, not a
    // sign-in that dies on the way back.
    vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => rememberReturnTo("/agents/a-1")).not.toThrow();
    expect(takeReturnTo()).toBeNull();
  });

  it("survives a refusal to clear as well as one to write", () => {
    vi.spyOn(window.sessionStorage, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => rememberReturnTo(null)).not.toThrow();
  });
});

describe("what an attempt started from this URL should remember", () => {
  const url = (query: string) => new URLSearchParams(query);

  it("takes the deep link the visitor arrived with", () => {
    expect(returnToForAttempt(url("returnTo=/agents/a-1"))).toBe("/agents/a-1");
  });

  it("takes nothing from a plain sign-in page", () => {
    rememberReturnTo("/agents/abandoned");

    expect(returnToForAttempt(url(""))).toBeNull();
  });

  it("keeps the path across a retry, where the URL has lost it", () => {
    // A failed provider attempt comes back to `/login?error=oauth_failed` with
    // no `returnTo` on it. Clearing there drops a path nobody abandoned.
    rememberReturnTo("/agents/a-1");

    expect(returnToForAttempt(url("error=oauth_failed"))).toBe("/agents/a-1");
  });

  it("prefers the URL's own deep link over what is stored", () => {
    rememberReturnTo("/agents/older");

    expect(returnToForAttempt(url("error=oauth_failed&returnTo=/agents/newer"))).toBe(
      "/agents/newer",
    );
  });

  it("answers with nothing on a retry that never carried one", () => {
    expect(returnToForAttempt(url("error=oauth_failed"))).toBeNull();
  });

  it("survives a browser that refuses to be read", () => {
    vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(returnToForAttempt(url("error=oauth_failed"))).toBeNull();
  });
});
