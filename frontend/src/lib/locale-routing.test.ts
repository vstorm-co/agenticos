import { describe, expect, it } from "vitest";

import { LOCALE_COOKIE_NAME, localePrefixOf, routing } from "@/lib/locale-routing";

describe("localePrefixOf", () => {
  it("names the locale a prefixed path carries", () => {
    expect(localePrefixOf("/pl/agents")).toBe("pl");
    expect(localePrefixOf("/pl")).toBe("pl");
    expect(localePrefixOf("/en/agents")).toBe("en");
  });

  it("answers null for a path that carries none", () => {
    expect(localePrefixOf("/agents")).toBeNull();
    expect(localePrefixOf("/")).toBeNull();
    expect(localePrefixOf("")).toBeNull();
  });

  it("does not mistake a route whose first segment merely starts with a locale", () => {
    expect(localePrefixOf("/plans")).toBeNull();
    expect(localePrefixOf("/environments")).toBeNull();
  });
});

describe("routing", () => {
  it("writes the cookie the middleware reads", () => {
    // The switch persists nothing if these two names drift apart, and the
    // symptom is silent: the URL prefix carries the locale for the current page.
    expect(routing.localeCookie).toMatchObject({ name: LOCALE_COOKIE_NAME });
  });

  it("keeps the locale beyond the browser session", () => {
    expect(routing.localeCookie).toMatchObject({ maxAge: 60 * 60 * 24 * 365 });
  });

  it("leaves accept-language sniffing off", () => {
    expect(routing.localeDetection).toBe(false);
    expect(routing.localePrefix).toBe("as-needed");
  });
});
