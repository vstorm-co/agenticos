"use client";

import { useTranslations } from "next-intl";
import type { ConversationAgent } from "@/types/conversation";
import type { CodingHarness } from "@/types/chat";

/** The i18n key naming each harness. The products' own names, so the new ones
 * read English in every locale (English sits underneath each locale). */
export const HARNESS_LABEL_KEY: Record<
  CodingHarness,
  "claudeCode" | "codex" | "opencode" | "gemini" | "pi"
> = {
  claude_code: "claudeCode",
  codex: "codex",
  opencode: "opencode",
  gemini: "gemini",
  pi: "pi",
};

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
  const names = [...platform, ...coding.map((harness) => tHarness(HARNESS_LABEL_KEY[harness]))];
  return names.length === 0 ? null : names.join(" · ");
}
