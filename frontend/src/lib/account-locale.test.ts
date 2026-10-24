import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import {
  ACCOUNT_LOCALE_STORAGE_KEY,
  adoptAccountLocale,
  localeChosenBy,
  sharedAccountLocale,
} from "./account-locale";

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
  locale: "pl",
};

beforeEach(() => {
  window.localStorage.removeItem(ACCOUNT_LOCALE_STORAGE_KEY);
  useAuthStore.setState({ user: ADA });
});

afterEach(() => vi.restoreAllMocks());

describe("sharedAccountLocale", () => {
  it("accepts a supported language for this account only", () => {
    expect(sharedAccountLocale('{"userId":"u-1","locale":"en"}', "u-1")).toBe("en");
    expect(sharedAccountLocale('{"userId":"u-2","locale":"de"}', "u-1")).toBeNull();
  });

  it.each([
    null,
    "broken",
    "[]",
    "null",
    '"en"',
    '{"locale":"en"}',
    '{"userId":"u-1","locale":"es"}',
  ])("ignores an absent or malformed choice: %s", (raw) =>
    expect(sharedAccountLocale(raw, "u-1")).toBeNull(),
  );
});

describe("localeChosenBy", () => {
  it("reads the language the platform's own tool set", () => {
    expect(localeChosenBy("agenticos_set_my_language", '{"locale": "en"}')).toBe("en");
  });

  it("trusts no other server's tool of the same name", () => {
    // Codex on #2324: an organization's or a person's own MCP server can expose a
    // `set_my_language` too; its answer is that server's, not this account's.
    expect(localeChosenBy("notion_set_my_language", '{"locale": "en"}')).toBeNull();
    expect(localeChosenBy("set_my_language", '{"locale": "de"}')).toBeNull();
  });

  it("reads nothing from another tool, a refusal or a language the console lacks", () => {
    expect(localeChosenBy("web_search", '{"locale": "en"}')).toBeNull();
    expect(localeChosenBy("agenticos_set_my_language", "403 FORBIDDEN: no")).toBeNull();
    expect(localeChosenBy("agenticos_set_my_language", '{"locale": "es"}')).toBeNull();
    expect(localeChosenBy("agenticos_set_my_language", '"en"')).toBeNull();
    expect(localeChosenBy("agenticos_set_my_language", "null")).toBeNull();
  });
});

describe("adoptAccountLocale", () => {
  it("records the choice on the signed-in account", () => {
    adoptAccountLocale("en");

    expect(useAuthStore.getState().user?.locale).toBe("en");
    expect(JSON.parse(window.localStorage.getItem(ACCOUNT_LOCALE_STORAGE_KEY) ?? "null")).toEqual({
      userId: "u-1",
      locale: "en",
    });
  });

  it("leaves the account as it is when nothing changes", () => {
    const before = useAuthStore.getState().user;

    adoptAccountLocale("pl");

    expect(useAuthStore.getState().user).toBe(before);
    expect(window.localStorage.getItem(ACCOUNT_LOCALE_STORAGE_KEY)).toBeNull();
  });

  it("does nothing with nobody signed in", () => {
    useAuthStore.setState({ user: null });

    adoptAccountLocale("en");

    expect(useAuthStore.getState().user).toBeNull();
    expect(window.localStorage.getItem(ACCOUNT_LOCALE_STORAGE_KEY)).toBeNull();
  });

  it("keeps the account's choice and reports a refused cross-window write", () => {
    const write = window.localStorage.setItem.bind(window.localStorage);
    vi.spyOn(window.localStorage, "setItem").mockImplementation((key, value) => {
      if (key === ACCOUNT_LOCALE_STORAGE_KEY) throw new DOMException("Storage is unavailable");
      write(key, value);
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    adoptAccountLocale("de");
    expect(useAuthStore.getState().user?.locale).toBe("de");
    expect(warn).toHaveBeenCalledOnce();
  });
});
