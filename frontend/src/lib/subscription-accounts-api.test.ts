import { expect, it } from "vitest";
import {
  subscriptionLabelMatches,
  subscriptionProviderFor,
  type SubscriptionProvider,
  type SubscriptionAccount,
} from "./subscription-accounts-api";

it.each<[SubscriptionProvider, string, string, boolean]>([
  ["kimi", "Kimi Code (kimi.com) · model", "Kimi Code (kimi.com)", true],
  ["kimi", "Kimi Code (Moonshot) · model", "Kimi Code (kimi.com)", true],
  ["kimi-ai", "Kimi (kimi.com) · model", "Kimi Code (kimi.ai)", true],
  ["kimi-ai", "Kimi Code (kimi.ai) · model", "Kimi Code (kimi.ai)", true],
  ["kimi", "Other · model", "Kimi Code (kimi.com)", false],
  ["kimi-ai", "Other · model", "Kimi Code (kimi.ai)", false],
  ["claude", "Kimi Code (Moonshot) · model", "Claude Code", false],
  ["claude", "Claude Code · model", "Claude Code", true],
])(
  "preserves the correct provider for existing %s profile labels",
  (provider, label, name, expected) => {
    expect(subscriptionLabelMatches(label, provider, name)).toBe(expected);
  },
);

const displayName = (provider: SubscriptionProvider) =>
  provider === "antigravity" ? "Google Antigravity" : provider;
it("restores subscription identity from account routing before profile labels", () => {
  const prefix = `account-${"a".repeat(24)}`;
  const account: SubscriptionAccount = {
    name: "one",
    provider: "gemini",
    model_prefix: prefix,
    label: null,
    email: null,
    status: "active",
    disabled: false,
    unavailable: false,
  };
  expect(
    subscriptionProviderFor(
      { provider: "subscription_accounts", model: `${prefix}/claude`, label: "codex · claude" },
      [account],
      displayName,
    ),
  ).toBe("antigravity");
  expect(
    subscriptionProviderFor(
      { provider: "subscription_accounts", model: "claude", label: "Google Antigravity · claude" },
      [account],
      displayName,
    ),
  ).toBe("antigravity");
  expect(
    subscriptionProviderFor(
      { provider: "subscription_accounts", model: `${prefix}/claude`, label: "codex · claude" },
      [{ ...account, provider: "unknown" }],
      displayName,
    ),
  ).toBe("codex");
});
it("does not guess a subscription from a model maker or an unrelated API profile", () => {
  expect(subscriptionProviderFor(null, [], displayName)).toBeUndefined();
  expect(subscriptionProviderFor(undefined, [], displayName)).toBeUndefined();
  expect(
    subscriptionProviderFor(
      { provider: "openai", model: "claude", label: "codex · claude" },
      [],
      displayName,
    ),
  ).toBeUndefined();
  expect(
    subscriptionProviderFor(
      { provider: "subscription_accounts", model: "claude", label: "Custom" },
      [],
      displayName,
    ),
  ).toBeUndefined();
});
