"use client";

import { useTranslations } from "next-intl";
import type { ConversationAgent } from "@/types/conversation";
import type { CodingHarness } from "@/types/chat";

/** Platform agents and coding harnesses stay distinct, while sharing one caption. */
export function useConversationAgentLabel(
  agents: readonly ConversationAgent[],
  coding: readonly CodingHarness[],
): string | null {
  const t = useTranslations("agents");
  const tHarness = useTranslations("chat.localAgent");
  const platform =
    agents.length === 0
      ? []
      : [agents.length === 1 ? agents[0]!.name : t("agentCount", { count: agents.length })];
  const names = [
    ...platform,
    ...coding.map((harness) => tHarness(harness === "codex" ? "codex" : "claudeCode")),
  ];
  return names.length === 0 ? null : names.join(" · ");
}
