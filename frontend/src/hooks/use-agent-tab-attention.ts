"use client";

import { useTranslations } from "next-intl";

import { useImprovements } from "@/hooks/use-improvements";
import { useKnowledgeGaps } from "@/hooks/use-knowledge-gaps";
import { useAgentAttention } from "@/hooks/use-usage-stats";
import { evalsAttention } from "@/lib/attention";
import { resolvePreset } from "@/lib/dashboard/period";
import { openImprovement } from "@/lib/improvement-steps";

/**
 * What an agent's tabs hold for the reader to act on: the reasons its Evals tab
 * carries a dot, and how many open knowledge gaps its Knowledge gaps tab does.
 *
 * Read over the same thirty days as the agent list's badge and the Improve
 * button, from the same cached answer, so the three never disagree. Asks
 * nothing while `enabled` is false - for a reader who may not see runs, whom
 * neither tab is offered to. An Improve session waiting for a person counts
 * only for a reader who `canEdit` the agent, the one who may continue it.
 */
export function useAgentTabAttention(
  agentId: string,
  { enabled = true, canEdit = false }: { enabled?: boolean; canEdit?: boolean } = {},
) {
  const t = useTranslations("attention");
  const lately = resolvePreset("30d");
  const { agents } = useAgentAttention({ from: lately.from, to: lately.to }, { enabled });
  const { sessions } = useImprovements(agentId, { enabled: enabled && canEdit });
  const { total } = useKnowledgeGaps(
    { kind: "agent", id: agentId },
    { status: "open", limit: 1, enabled },
  );
  if (!enabled) return { evals: [], gaps: 0 };
  return {
    evals: evalsAttention(
      agents.find((agent) => agent.agent_id === agentId),
      canEdit ? openImprovement(sessions) : undefined,
      t,
    ),
    gaps: total,
  };
}
