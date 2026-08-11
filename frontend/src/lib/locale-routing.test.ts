import { describe, expect, it } from "vitest";

import { LOCALE_COOKIE_NAME, localePrefixOf, pickedLocale, routing } from "@/lib/locale-routing";

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

  it("names it whatever case the path wrote it in", () => {
    // next-intl matches a prefix case-insensitively, so a path it treats as Polish
    // must be treated as Polish here too - see `middleware.test.ts` for what a
    // disagreement costs.
    expect(localePrefixOf("/PL/agents")).toBe("pl");
    expect(localePrefixOf("/En")).toBe("en");
  });
});

describe("pickedLocale", () => {
  it("names a locale this deployment serves", () => {
    expect(pickedLocale("pl")).toBe("pl");
  });

  it("answers null for the default, which needs no prefix", () => {
    expect(pickedLocale("en")).toBeNull();
  });

  it("answers null for nothing, for empty, and for a locale we do not serve", () => {
    expect(pickedLocale(undefined)).toBeNull();
    expect(pickedLocale("")).toBeNull();
    expect(pickedLocale("de")).toBeNull();
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
