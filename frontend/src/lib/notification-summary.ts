import type { Translate } from "@/lib/agent-step-captions";
import { ATTEMPT_RESULT_REASONS } from "@/lib/improvement-steps";
import type { Notification } from "@/lib/notifications-api";

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
  const outcome = item.outcome;
  if (!outcome) return item.summary;
  if (item.event_type === "improvement_finished" && outcome.status === "waiting") {
    if (!item.agent?.name) return item.summary;
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
