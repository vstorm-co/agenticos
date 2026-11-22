import type { Translate } from "@/lib/agent-step-captions";
import { isActive } from "@/lib/improvement-steps";
import type { Improvement } from "@/types/improvement";
import type { AgentAttention } from "@/types/stats";

/** What makes an agent need attention, as the parts a line lists - each one that is not zero. */
export function attentionParts(item: AgentAttention, t: Translate): string[] {
  return [
    item.rated_down > 0 ? t("rated", { count: item.rated_down }) : null,
    item.failed_runs > 0 ? t("failed", { count: item.failed_runs }) : null,
    item.failing_suites > 0 ? t("suites", { count: item.failing_suites }) : null,
  ].filter((part): part is string => part !== null);
}

/** Answers rated down or runs that failed: what Improve works from, and what its dot marks. */
export function improveNeeded(item: AgentAttention | undefined): item is AgentAttention {
  return item !== undefined && (item.rated_down > 0 || item.failed_runs > 0);
}

/**
 * Why an agent's Evals tab holds something waiting for the reader: what the agent
 * needs attention for, and an Improve session stopped for a person. A session still
 * working waits for nobody. None means the tab carries no dot.
 */
export function evalsAttention(
  item: AgentAttention | undefined,
  session: Pick<Improvement, "status"> | undefined,
  t: Translate,
): string[] {
  const reasons = item ? attentionParts(item, t) : [];
  return session && !isActive(session) ? [...reasons, t("improvementWaiting")] : reasons;
}
