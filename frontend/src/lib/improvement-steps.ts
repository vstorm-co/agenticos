import type { Improvement } from "@/types/improvement";

export const IMPROVEMENT_STEPS = [
  "understand",
  "testSet",
  "changes",
  "check",
  "result",
  "accept",
] as const;
export type ImprovementStep = (typeof IMPROVEMENT_STEPS)[number];
export type ImprovementStepState = "done" | "running" | "needs_you" | "skipped" | "pending";

/** What a step's panel shows: work in progress, stored work, or nothing yet. */
export type ImprovementStepContent = "working" | "result" | "none";

export interface ImprovementStepView {
  state: ImprovementStepState;
  content: ImprovementStepContent;
}

const PROPOSING: readonly string[] = ["proposing", "filtering", "drafting"];
const CHECKING: readonly string[] = ["evaluating", "judging"];

export function isActive(session: Pick<Improvement, "status">): boolean {
  return session.status === "queued" || session.status === "running";
}

/** The attempt the session is on now: repeating steps describe it, not an earlier one. */
export function currentAttempt(session: Improvement) {
  return (
    session.iterations.find((round) => round.number === session.iteration) ??
    session.iterations.at(-1)
  );
}

/** A checked candidate waits for a person to accept it. */
export function hasCandidate(session: Improvement): boolean {
  return session.status === "ready" && session.best_iteration_id !== null;
}

export function currentImprovementStep(session: Improvement): ImprovementStep {
  if (session.status === "accepted" || session.status === "published") return "accept";
  if (!isActive(session)) return "result";
  if (CHECKING.includes(session.stage ?? "")) return "check";
  if (PROPOSING.includes(session.stage ?? "")) return "changes";
  return "understand";
}

/**
 * Each step's state and what its panel shows, from one reading of the session, so
 * the stepper and the panels cannot disagree: a running step's panel says it is
 * working, and a done step's shows what it stored. Changes and Check follow the
 * current attempt, so a new attempt runs them again. Result and Accept open only
 * once the session stops working.
 */
export function improvementSteps(
  session: Improvement,
): Record<ImprovementStep, ImprovementStepView> {
  const active = isActive(session);
  const accepted = session.status === "accepted" || session.status === "published";
  const decided = accepted || session.status === "rejected";
  const stage = session.stage ?? "";
  const attempt = currentAttempt(session);
  const later = session.iteration > 1;
  const noData = session.stop_reason === "no_data";
  const groupingFailed = session.timeline.some(
    (event) => event.action === "improvement.classification_failed",
  );
  const states: Record<ImprovementStep, ImprovementStepState> = {
    understand:
      active && (!session.stage || ["analyzing", "classifying"].includes(stage))
        ? "running"
        : noData || (!decided && groupingFailed)
          ? "needs_you"
          : session.stage
            ? "done"
            : "skipped",
    testSet: noData || session.status === "stale" ? "needs_you" : "done",
    changes: accepted
      ? "done"
      : session.status === "rejected"
        ? "skipped"
        : active && PROPOSING.includes(stage)
          ? "running"
          : session.stop_reason === "knowledge_only"
            ? "needs_you"
            : active
              ? attempt?.batch_id
                ? "done"
                : "pending"
              : session.iterations.some((round) => round.batch_id !== null)
                ? "done"
                : "skipped",
    check:
      active && (CHECKING.includes(stage) || later)
        ? "running"
        : active
          ? "pending"
          : session.iterations.some((round) => round.verdict !== null)
            ? "done"
            : "skipped",
    result: active
      ? "pending"
      : decided || session.status === "ready"
        ? "done"
        : session.stop_reason === "knowledge_only"
          ? "skipped"
          : "needs_you",
    accept: accepted
      ? "done"
      : hasCandidate(session)
        ? "needs_you"
        : active
          ? "pending"
          : "skipped",
  };
  const view = (state: ImprovementStepState): ImprovementStepView => ({
    state,
    content:
      state === "running"
        ? "working"
        : state === "done" || state === "needs_you"
          ? "result"
          : "none",
  });
  return Object.fromEntries(IMPROVEMENT_STEPS.map((step) => [step, view(states[step])])) as Record<
    ImprovementStep,
    ImprovementStepView
  >;
}

/** The states alone, for a caller that draws only the stepper. */
export function improvementStepStates(
  session: Improvement,
): Record<ImprovementStep, ImprovementStepState> {
  const views = improvementSteps(session);
  return Object.fromEntries(IMPROVEMENT_STEPS.map((step) => [step, views[step].state])) as Record<
    ImprovementStep,
    ImprovementStepState
  >;
}

/** Whether a person may open this step: only one with something to show or to decide. */
export function isReachable(view: ImprovementStepView): boolean {
  return view.state === "done" || view.state === "running" || view.state === "needs_you";
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
