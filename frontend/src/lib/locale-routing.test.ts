import { describe, expect, it } from "vitest";

import {
  LOCALE_COOKIE_NAME,
  localePrefixOf,
  pickedLocale,
  routing,
  withoutRetiredPrefix,
} from "@/lib/locale-routing";
import { hasLocaleChoice, locales } from "@/lib/locales";

describe("the locales this fork serves", () => {
  it("are English alone, so no language control renders", () => {
    expect(locales).toEqual(["en"]);
    expect(hasLocaleChoice).toBe(false);
  });
});

describe("localePrefixOf", () => {
  it("names the locale a prefixed path carries", () => {
    expect(localePrefixOf("/en/agents")).toBe("en");
    expect(localePrefixOf("/en")).toBe("en");
  });

  it("answers null for a path that carries none", () => {
    expect(localePrefixOf("/agents")).toBeNull();
    expect(localePrefixOf("/")).toBeNull();
    expect(localePrefixOf("")).toBeNull();
  });

  it("answers null for a retired locale, which this fork does not serve", () => {
    expect(localePrefixOf("/pl/agents")).toBeNull();
    expect(localePrefixOf("/de/agents")).toBeNull();
    expect(localePrefixOf("/tr/login")).toBeNull();
  });

  it("does not mistake a route whose first segment merely starts with a locale", () => {
    expect(localePrefixOf("/environments")).toBeNull();
  });

  it("names it whatever case the path wrote it in", () => {
    // next-intl matches a prefix case-insensitively - see `middleware.test.ts`.
    expect(localePrefixOf("/En")).toBe("en");
  });
});

describe("withoutRetiredPrefix", () => {
  it("strips a retired locale's prefix, whatever its case", () => {
    expect(withoutRetiredPrefix("/pl/agents")).toBe("/agents");
    expect(withoutRetiredPrefix("/DE/agents/abc")).toBe("/agents/abc");
    expect(withoutRetiredPrefix("/tr")).toBe("/");
  });

  it("answers null for every other path", () => {
    expect(withoutRetiredPrefix("/agents")).toBeNull();
    expect(withoutRetiredPrefix("/en/agents")).toBeNull();
    expect(withoutRetiredPrefix("/plans")).toBeNull();
    expect(withoutRetiredPrefix("/")).toBeNull();
    expect(withoutRetiredPrefix("")).toBeNull();
  });
});

describe("pickedLocale", () => {
  it("answers null for the default, which needs no prefix", () => {
    expect(pickedLocale("en")).toBeNull();
  });

  it("answers null for nothing, for empty, and for a locale we do not serve", () => {
    expect(pickedLocale(undefined)).toBeNull();
    expect(pickedLocale("")).toBeNull();
    expect(pickedLocale("fr")).toBeNull();
    expect(pickedLocale("pl")).toBeNull();
    expect(pickedLocale("es")).toBeNull();
  });
});

describe("routing", () => {
  it("writes the cookie the middleware reads", () => {
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
