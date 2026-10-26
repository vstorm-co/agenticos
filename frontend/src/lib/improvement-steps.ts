import type { Improvement } from "@/types/improvement";

export const IMPROVEMENT_STEPS = [
  "understand",
  "testSet",
  "today",
  "changes",
  "check",
  "result",
  "accept",
] as const;
export type ImprovementStep = (typeof IMPROVEMENT_STEPS)[number];
export type ImprovementStepState = "done" | "running" | "needs_you" | "skipped" | "pending";

export function currentImprovementStep(session: Improvement): ImprovementStep {
  if (session.status === "accepted" || session.status === "published") return "accept";
  if (session.status !== "queued" && session.status !== "running") return "result";
  if (session.stage === "evaluating" || session.stage === "judging") return "check";
  if (["proposing", "filtering", "drafting"].includes(session.stage ?? "")) return "changes";
  return "understand";
}

/** Report stored work independently of which step the person is inspecting. */
export function improvementStepStates(
  session: Improvement,
): Record<ImprovementStep, ImprovementStepState> {
  const active = session.status === "queued" || session.status === "running";
  const accepted = session.status === "accepted" || session.status === "published";
  const decided = accepted || session.status === "rejected";
  const measured = session.iterations.some((round) => round.verdict !== null);
  const hasChanges = session.iterations.some((round) => round.batch_id !== null);
  const testing = active && (session.stage === "evaluating" || session.stage === "judging");
  const analyzing =
    active && (!session.stage || ["analyzing", "classifying"].includes(session.stage));
  const drafting = active && ["proposing", "filtering", "drafting"].includes(session.stage ?? "");
  const noData = session.stop_reason === "no_data";
  const groupingFailed = session.timeline.some(
    (event) => event.action === "improvement.classification_failed",
  );
  return {
    understand: analyzing
      ? "running"
      : noData || (!decided && groupingFailed)
        ? "needs_you"
        : session.stage
          ? "done"
          : "skipped",
    testSet: noData || session.status === "stale" ? "needs_you" : "done",
    today: measured ? "done" : testing ? "running" : active ? "pending" : "skipped",
    changes: accepted
      ? "done"
      : session.status === "rejected"
        ? "skipped"
        : drafting
          ? "running"
          : session.stop_reason === "knowledge_only"
            ? "needs_you"
            : hasChanges
              ? "done"
              : active
                ? "pending"
                : "skipped",
    check: testing ? "running" : measured ? "done" : active ? "pending" : "skipped",
    result: decided
      ? "done"
      : active
        ? "pending"
        : session.stop_reason === "knowledge_only"
          ? "skipped"
          : "needs_you",
    // While a result waits, it is the one decision; Accept follows from it.
    accept: accepted
      ? "done"
      : ["failed", "cancelled", "stale", "rejected"].includes(session.status)
        ? "skipped"
        : "pending",
  };
}

/**
 * Still working, or waiting for a person's decision: a candidate to accept, or a
 * stopped or failed session to continue, retry or discard.
 */
const OPEN: readonly string[] = ["queued", "running", "ready", "stopped", "failed"];

/** Over for good: the API refuses any change, so the session is read as a record. */
const CLOSED: readonly string[] = ["accepted", "published", "rejected", "cancelled", "stale"];

/**
 * The newest session Improve should take somebody back to, if the agent has one.
 *
 * Only an open one: a session that was decided, cancelled or outdated is in the
 * agent's improvement history, and Improve starts the next session instead.
 */
export function openImprovement(sessions: Improvement[]): Improvement | undefined {
  return sessions
    .filter((session) => OPEN.includes(session.status))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

/** Whether nothing can change the session any more. */
export function isClosed(session: Pick<Improvement, "status">): boolean {
  return CLOSED.includes(session.status);
}
