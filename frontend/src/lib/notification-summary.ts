import type { Translate } from "@/lib/agent-step-captions";
import { ATTEMPT_RESULT_REASONS } from "@/lib/improvement-steps";
import type { Notification } from "@/lib/notifications-api";
import { formatCostUsd } from "@/lib/utils";

const IMPROVEMENT = ["ready", "stopped", "failed", "stale"];
const TEST = ["completed", "failed", "cancelled", "budget_exceeded"];
const GENERATION = ["ready", "failed"];
const STOP_REASONS = [
  "no_data",
  "no_proposal",
  "budget",
  "inconclusive",
  "regression",
  "no_change",
  "max_iterations",
  "repeat_candidate",
  "permission",
  "stale",
  "stalled",
  "proposal",
  "eval",
  "superseded",
  "knowledge_only",
  "draft",
  "expired",
];

/**
 * A finished improvement or one stopped for a person, a test or question writing in the
 * reader's language, from the outcome the server keeps beside its English summary;
 * anything else, or a status this console does not know yet, keeps that summary.
 */
export function notificationSummary(item: Notification, t: Translate, tStop: Translate): string {
  const worded = paramsSummary(item, t);
  if (worded !== null) return worded;
  const outcome = item.outcome;
  if (!outcome) return item.summary;
  if (item.event_type === "improvement_finished" && outcome.status === "waiting") {
    if (!item.agent?.name) return item.summary;
    if (outcome.next_step_blocked)
      return t("outcome.improvement.waiting.blocked", {
        agent: item.agent.name,
        needed: outcome.next_step_blocked.needed,
      });
    const stage = outcome.stage ?? outcome.reason;
    return t(`outcome.improvement.waiting.${stage === "filtering" ? "changes" : "understand"}`, {
      agent: item.agent.name,
    });
  }
  if (item.event_type === "improvement_finished" && IMPROVEMENT.includes(outcome.status)) {
    if (!item.agent?.name) return item.summary;
    // A session ended as stale is said the way a stopped one is, with why it ended.
    const status =
      outcome.status === "stale"
        ? "stopped"
        : outcome.status === "stopped" && ATTEMPT_RESULT_REASONS.includes(outcome.reason ?? "")
          ? "attemptFinished"
          : outcome.status;
    const head = t(`outcome.improvement.${status}`, { agent: item.agent.name });
    return outcome.status !== "ready" && outcome.reason && STOP_REASONS.includes(outcome.reason)
      ? `${head} ${tStop(outcome.reason)}`
      : head;
  }
  if (item.event_type === "eval_run_finished" && TEST.includes(outcome.status))
    return t(`outcome.test.${outcome.status}`);
  if (item.event_type === "case_generation_finished" && GENERATION.includes(outcome.status))
    return t(`outcome.questions.${outcome.status}`);
  return item.summary;
}

/** Dollars to the cent, or to the place spend is shown at when the cent would read as nothing. */
function usd(value: string): string {
  const amount = Number(value);
  return amount > 0 && amount < 0.01 ? formatCostUsd(amount) : `$${amount.toFixed(2)}`;
}

/** An approval request or a budget limit, worded from the values the server kept. */
function paramsSummary(item: Notification, t: Translate): string | null {
  const params = item.params;
  if (!params) return null;
  switch (item.event_type) {
    case "approval_requested":
      return t("kind.approvalRequested", { agent: params.agent_name ?? "" });
    case "budget_exceeded":
      return t("kind.budgetExceeded", {
        agent: params.agent_name ?? "",
        // A department's cap names its department when the row says which.
        scope: params.scope === "group" && params.subject ? "department" : (params.scope ?? ""),
        department: params.subject ?? "",
        spent: formatCostUsd(Number(params.spent_usd ?? "0")),
        limit: usd(params.limit_usd ?? "0"),
      });
    case "budget_warning":
      return t("kind.budgetWarning", {
        group: params.group_name ?? "",
        share: params.share ?? "",
        limit: usd(params.limit ?? "0"),
      });
    default:
      return null;
  }
}
