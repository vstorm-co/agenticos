import { expect, it } from "vitest";
import { subscriptionLabelMatches, type SubscriptionProvider } from "./subscription-accounts-api";

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
