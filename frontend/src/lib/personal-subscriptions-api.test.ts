import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import {
  cancelClaudeSubscriptionLogin,
  claudeAuthorizationUrl,
  claudeSignInPending,
  claudeSubscriptionPollInterval,
  disconnectClaudeSubscription,
  readClaudeSubscription,
  startClaudeSubscriptionLogin,
  submitClaudeSubscriptionCode,
} from "./personal-subscriptions-api";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

const disconnected: ClaudeSubscriptionStatus = {
  available: true,
  connected: false,
  state: "disconnected",
  login_id: null,
  authorization_url: null,
  expires_at: null,
  error_code: null,
};
beforeEach(() => vi.clearAllMocks());

it("keeps status and every sign-in action on the authenticated same-origin API", async () => {
  const signal = new AbortController().signal;
  await readClaudeSubscription(signal);
  await startClaudeSubscriptionLogin(signal);
  await submitClaudeSubscriptionCode("login-1", "page-code", signal);
  await cancelClaudeSubscriptionLogin("login-1", signal);
  await disconnectClaudeSubscription(signal);
  expect(apiClient.get).toHaveBeenCalledWith("/personal-subscriptions/claude", { signal });
  expect(apiClient.post).toHaveBeenNthCalledWith(
    1,
    "/personal-subscriptions/claude/login",
    {},
    { signal },
  );
  expect(apiClient.post).toHaveBeenNthCalledWith(
    2,
    "/personal-subscriptions/claude/login/code",
    { login_id: "login-1", code: "page-code" },
    { signal },
  );
  expect(apiClient.post).toHaveBeenNthCalledWith(
    3,
    "/personal-subscriptions/claude/login/cancel",
    { login_id: "login-1" },
    { signal },
  );
  expect(apiClient.post).toHaveBeenNthCalledWith(
    4,
    "/personal-subscriptions/claude/disconnect",
    {},
    { signal },
  );
});

describe("provider authorization links", () => {
  it.each([
    "https://claude.ai/oauth/authorize?state=opaque",
    "https://claude.ai:443/oauth/authorize/",
    "https://claude.com/cai/oauth/authorize?state=opaque",
    "https://claude.com:443/cai/oauth/authorize/",
  ])("allows the official HTTPS authorization page: %s", (url) => {
    expect(claudeAuthorizationUrl(url)).toBe(new URL(url).href);
  });

  it.each([
    null,
    "not a URL",
    "javascript:alert(1)",
    "http://claude.ai/oauth/authorize",
    "https://claude.ai.evil.test/oauth/authorize",
    "https://evil.test/claude.ai/oauth/authorize",
    "https://claude.ai:8443/oauth/authorize",
    "https://user:password@claude.ai/oauth/authorize",
    "https://claude.ai/chat",
    "https://claude.com/oauth/authorize",
    "https://claude.ai/cai/oauth/authorize",
    "https://claude.com.evil.test/cai/oauth/authorize",
    "https://user@claude.com/cai/oauth/authorize",
    "https://claude.com:8443/cai/oauth/authorize",
    "https://claude.com/cai/oauth/authorize#fragment",
    "https://claude.ai/oauth/authorize#fragment",
    "https://console.anthropic.com/oauth/authorize",
    `https://claude.ai/oauth/authorize?state=${"a".repeat(8_192)}`,
  ])("refuses a different origin, path, protocol or malformed link", (url) => {
    expect(claudeAuthorizationUrl(url)).toBeNull();
  });
});

describe("bounded native status polling", () => {
  const now = Date.parse("2026-11-07T12:00:00Z");
  it.each(["starting", "awaiting_code", "verifying"] as const)(
    "polls %s only until its deadline and final status check",
    (state) => {
      const pending = { ...disconnected, state, expires_at: "2026-11-07T12:10:00Z" };
      expect(claudeSignInPending(pending)).toBe(true);
      expect(claudeSubscriptionPollInterval(pending, now)).toBe(1_500);
      expect(claudeSubscriptionPollInterval(pending, now + 600_001)).toBe(1_500);
      expect(claudeSubscriptionPollInterval(pending, now + 605_001)).toBe(false);
    },
  );
  it.each([
    undefined,
    disconnected,
    { ...disconnected, state: "connected" as const },
    { ...disconnected, state: "error" as const },
  ])("does not keep probing a connection outside sign-in", (state) => {
    expect(claudeSignInPending(state)).toBe(false);
    expect(claudeSubscriptionPollInterval(state, now)).toBe(false);
  });
  it("stops if a runtime supplies no valid deadline", () => {
    expect(claudeSubscriptionPollInterval({ ...disconnected, state: "starting" }, now)).toBe(false);
    expect(
      claudeSubscriptionPollInterval(
        { ...disconnected, state: "starting", expires_at: "invalid" },
        now,
      ),
    ).toBe(false);
  });
});
