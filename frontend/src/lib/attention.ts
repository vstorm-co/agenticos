import type { Translate } from "@/lib/agent-step-captions";
import type { AgentAttention } from "@/types/stats";

/** What makes an agent need attention, as the parts a line lists - each one that is not zero. */
export function attentionParts(item: AgentAttention, t: Translate): string[] {
  return [
    item.rated_down > 0 ? t("rated", { count: item.rated_down }) : null,
    item.failed_runs > 0 ? t("failed", { count: item.failed_runs }) : null,
    item.failing_suites > 0 ? t("suites", { count: item.failing_suites }) : null,
  ].filter((part): part is string => part !== null);
}
