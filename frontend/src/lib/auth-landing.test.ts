import { describe, expect, it } from "vitest";

import { postSignInDestination } from "./auth-landing";
import { ROUTES } from "./constants";

describe("postSignInDestination", () => {
  it("defaults to the dashboard", () => {
    expect(postSignInDestination()).toBe(ROUTES.DASHBOARD);
    expect(postSignInDestination(null)).toBe(ROUTES.DASHBOARD);
  });

  it("honours a same-origin path, query included", () => {
    expect(postSignInDestination("/agents/a-1")).toBe("/agents/a-1");
    expect(postSignInDestination("/chat?id=c-1")).toBe("/chat?id=c-1");
  });

  // None is "fixed up" into something safe: a sanitised open redirect is
  // still an open redirect.
  it.each([
    "//evil.example/phish",
    "/\\evil.example",
    "https://evil.example",
    "javascript:alert(1)",
    "agents",
    "",
  ])("refuses %j and falls back to the dashboard", (path) => {
    expect(postSignInDestination(path)).toBe(ROUTES.DASHBOARD);
  });
});
