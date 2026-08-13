import { describe, expect, it } from "vitest";

import { isPublicSurface } from "./public-surfaces";

describe("isPublicSurface", () => {
  it.each(["/e/W-Buc9zD7bZOzro8FYEOmOpGrNxFGuN7", "/shared/abc123"])(
    "recognises %s as served to somebody who is not a member",
    (pathname) => {
      expect(isPublicSurface(pathname)).toBe(true);
    },
  );

  it.each(["/", "/chat", "/agents/abc", "/legal/cookies", "/login"])(
    "leaves %s alone",
    (pathname) => {
      expect(isPublicSurface(pathname)).toBe(false);
    },
  );

  it("does not match a route that merely starts with the same letters", () => {
    // The trailing slash in each prefix is what separates `/e/<key>` from a future
    // `/environments` - a bare `startsWith("/e")` would take the whole alphabet's
    // worth of pages out of scope for anything gated on this.
    expect(isPublicSurface("/environments")).toBe(false);
    expect(isPublicSurface("/sharedrafts")).toBe(false);
  });

  it("expects the locale prefix already gone", () => {
    // Not a wish: `usePathname` from `@/lib/locale-navigation` answers without it,
    // and this asserts the consequence of reading the other one by mistake, so the
    // failure names the cause rather than presenting as "no banner for Poles".
    expect(isPublicSurface("/pl/e/abc")).toBe(false);
  });
});
