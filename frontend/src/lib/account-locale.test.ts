import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import { adoptAccountLocale, localeChosenBy } from "./account-locale";

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
  locale: "pl",
};

beforeEach(() => useAuthStore.setState({ user: ADA }));

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
  });

  it("leaves the account as it is when nothing changes", () => {
    const before = useAuthStore.getState().user;

    adoptAccountLocale("pl");

    expect(useAuthStore.getState().user).toBe(before);
  });

  it("does nothing with nobody signed in", () => {
    useAuthStore.setState({ user: null });

    adoptAccountLocale("en");

    expect(useAuthStore.getState().user).toBeNull();
  });
});
