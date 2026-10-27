import { describe, expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import {
  currentAttempt,
  currentImprovementStep,
  hasCandidate,
  isActive,
  improvementStepStates,
  improvementSteps,
  isClosed,
  isReachable,
  openImprovement,
  stopOf,
} from "./improvement-steps";

const unmeasured = SESSION.iterations.map((round) => ({ ...round, verdict: null, batch_id: null }));
it.each([
  [null, "understand"],
  ["analyzing", "understand"],
  ["classifying", "understand"],
  ["drafting", "changes"],
  ["proposing", "changes"],
  ["filtering", "changes"],
  ["evaluating", "check"],
  ["judging", "check"],
] as const)("opens %s work at the current step without marking future work done", (stage, step) => {
  const session: Improvement = { ...SESSION, status: "running", stage, iterations: unmeasured };
  expect(currentImprovementStep(session)).toBe(step);
  const states = improvementStepStates(session);
  expect(states[step]).toBe("running");
  expect(states.result).toBe("pending");
  expect(states.accept).toBe("pending");
});
it("keeps the frozen question set readable while a new session waits", () => {
  const session: Improvement = { ...SESSION, status: "queued", stage: null, iterations: [] };
  const states = improvementStepStates(session);
  expect(states.changes).toBe("pending");
});
it("shows the current check running even if an earlier round was measured", () => {
  const states = improvementStepStates({
    ...SESSION,
    status: "running",
    stage: "evaluating",
  });
  expect(states.check).toBe("running");
  expect(states.changes).toBe("done");
});
it("asks for one decision at a time: a ready result waits on acceptance", () => {
  const states = improvementStepStates({ ...SESSION, status: "ready", stage: "judging" });
  expect(Object.values(states).filter((state) => state === "needs_you")).toHaveLength(1);
  expect(states).toMatchObject({ changes: "done", result: "done", accept: "needs_you" });
});
it("sends a session that only needs knowledge to its drafts rather than to a result", () => {
  const states = improvementStepStates({
    ...SESSION,
    status: "stopped",
    stop_reason: "knowledge_only",
    iterations: [{ ...SESSION.iterations[0]!, batch_id: null, verdict: null }],
  });
  expect(states).toMatchObject({ changes: "needs_you", result: "skipped" });
});
it.each(["accepted", "published"] as const)(
  "reopens %s sessions at the completed acceptance",
  (status) => {
    const session: Improvement = { ...SESSION, status };
    expect(currentImprovementStep(session)).toBe("accept");
    expect(improvementStepStates(session)).toMatchObject({
      accept: "done",
      result: "done",
      changes: "done",
    });
  },
);
it("shows a rejected proposal as skipped, not accepted", () => {
  expect(improvementStepStates({ ...SESSION, status: "rejected" })).toMatchObject({
    changes: "skipped",
    accept: "skipped",
    result: "done",
  });
});
it.each(["failed", "cancelled", "stale"] as const)(
  "does not invent a baseline after %s unmeasured work",
  (status) => {
    const session: Improvement = { ...SESSION, status, stage: null, iterations: unmeasured };
    expect(currentImprovementStep(session)).toBe("result");
    expect(improvementStepStates(session)).toMatchObject({
      check: "skipped",
      understand: "skipped",
      changes: "skipped",
      accept: "skipped",
    });
  },
);
it("marks the question set as needing attention when analysis stopped for lack of data", () => {
  expect(
    improvementStepStates({
      ...SESSION,
      status: "stopped",
      stage: "analyzing",
      stop_reason: "no_data",
      iterations: unmeasured,
    }),
  ).toMatchObject({ understand: "needs_you" });
});
it("leaves knowledge-only drafts for a person and skips the unrun agent test", () => {
  expect(
    improvementStepStates({
      ...SESSION,
      status: "stopped",
      stage: "drafting",
      stop_reason: "knowledge_only",
      iterations: unmeasured,
    }),
  ).toMatchObject({ changes: "needs_you", check: "skipped", understand: "done" });
});
it("does not disguise failed grouping as a completed analysis decision", () => {
  expect(
    improvementStepStates({
      ...SESSION,
      timeline: [
        {
          action: "improvement.classification_failed",
          at: SESSION.created_at,
          stage: "classifying",
          status: "running",
          reason: null,
        },
      ],
    }).understand,
  ).toBe("needs_you");
});
it("treats a running session with no current stage as analysis", () => {
  expect(currentImprovementStep({ ...SESSION, status: "running", stage: null })).toBe("understand");
  expect(
    improvementStepStates({ ...SESSION, status: "running", stage: null, iterations: [] }).check,
  ).toBe("pending");
});

it.each([
  ["queued", true, false],
  ["running", true, false],
  ["ready", true, false],
  ["stopped", true, false],
  ["failed", true, false],
  ["accepted", false, true],
  ["published", false, true],
  ["rejected", false, true],
  ["cancelled", false, true],
  ["stale", false, true],
] as const)(
  "a %s session is open to Improve: %s, and closed for good: %s",
  (status, open, closed) => {
    const session: Improvement = { ...SESSION, status };
    expect(openImprovement([session])).toBe(open ? session : undefined);
    expect(isClosed(session)).toBe(closed);
  },
);

it("takes Improve back to the newest open session, past any that finished since", () => {
  const older: Improvement = { ...SESSION, id: "older", status: "ready", created_at: "2026-10-01" };
  const newer: Improvement = {
    ...SESSION,
    id: "newer",
    status: "running",
    created_at: "2026-10-02",
  };
  const kept: Improvement = {
    ...SESSION,
    id: "kept",
    status: "accepted",
    created_at: "2026-10-03",
  };
  expect(openImprovement([older, kept, newer])?.id).toBe("newer");
});

it("has five steps: the question set is chosen at the start, today's answers in Check", () => {
  expect(Object.keys(improvementSteps(SESSION))).toEqual([
    "understand",
    "changes",
    "check",
    "result",
    "accept",
  ]);
});

it("skips Accept when there is nothing to accept, and opens it for a waiting candidate", () => {
  expect(hasCandidate({ ...SESSION, status: "ready" })).toBe(true);
  expect(hasCandidate({ ...SESSION, status: "ready", best_iteration_id: null })).toBe(false);
  expect(
    improvementStepStates({ ...SESSION, status: "stopped", best_iteration_id: null }).accept,
  ).toBe("skipped");
  const ready = improvementSteps({ ...SESSION, status: "ready" });
  expect(ready.accept).toEqual({ state: "needs_you", content: "result" });
  expect(isReachable(ready.accept)).toBe(true);
  expect(isReachable({ state: "pending", content: "none" })).toBe(false);
  expect(isReachable({ state: "skipped", content: "none" })).toBe(false);
});

it("follows the attempt the session is on, or the last one recorded", () => {
  const [first] = SESSION.iterations;
  const second = { ...first!, id: "r2", number: 2 };
  expect(currentAttempt({ ...SESSION, iteration: 2, iterations: [first!, second] })?.id).toBe("r2");
  expect(currentAttempt({ ...SESSION, iteration: 5, iterations: [first!, second] })?.id).toBe("r2");
  expect(currentAttempt({ ...SESSION, iterations: [] })).toBeUndefined();
});

it("runs Changes and Check again for a later attempt and shows nothing before the first check", () => {
  const [first] = SESSION.iterations;
  const later = improvementSteps({
    ...SESSION,
    status: "running",
    stage: "proposing",
    iteration: 2,
    iterations: [first!, { ...first!, id: "r2", number: 2, batch_id: null, verdict: null }],
  });
  expect(later.changes.state).toBe("running");
  expect(later.check.state).toBe("running");
  const checking = improvementSteps({
    ...SESSION,
    status: "running",
    stage: "evaluating",
    iteration: 2,
    iterations: [first!, { ...first!, id: "r2", number: 2, verdict: null }],
  });
  expect(checking.changes).toEqual({ state: "done", content: "result" });
  const firstProposal = improvementSteps({
    ...SESSION,
    status: "running",
    stage: "proposing",
    iterations: [{ ...first!, batch_id: null, verdict: null }],
  });
  expect(firstProposal.check).toEqual({ state: "pending", content: "none" });
  const firstCheck = improvementSteps({
    ...SESSION,
    status: "running",
    stage: "analyzing",
    iterations: [],
  });
  expect(firstCheck.changes.state).toBe("pending");
});

describe("a session stopped for a person", () => {
  const waiting = (stage: Improvement["stage"], iteration = 1): Improvement => ({
    ...SESSION,
    status: "waiting",
    stage,
    iteration,
    best_iteration_id: null,
    iterations: SESSION.iterations.map((round) => ({ ...round, verdict: null })),
  });
  it.each([
    ["analyzing", "understand", { understand: "needs_you", changes: "pending" }],
    ["classifying", "understand", { understand: "needs_you", changes: "pending" }],
    ["filtering", "changes", { understand: "done", changes: "needs_you" }],
  ] as const)("waiting after %s stops at %s", (stage, at, expected) => {
    const session = waiting(stage);
    expect(stopOf(session)).toBe(at);
    expect(currentImprovementStep(session)).toBe(at);
    const views = improvementSteps(session);
    expect(views).toMatchObject(
      Object.fromEntries(Object.entries(expected).map(([step, state]) => [step, { state }])),
    );
    expect(views[at].content).toBe("result");
    for (const step of ["check", "result", "accept"] as const)
      expect(views[step]).toEqual({ state: "pending", content: "none" });
    expect(Object.values(views).some((view) => view.state === "running")).toBe(false);
    expect(isActive(session)).toBe(false);
  });
  it("stops at the Changes of a later attempt without calling its check running", () => {
    const views = improvementSteps(waiting("filtering", 2));
    expect(views.changes.state).toBe("needs_you");
    expect(views.check.state).toBe("pending");
  });
  it("keeps a waiting session open, and finds no stop on one that is not waiting", () => {
    expect(
      openImprovement([{ ...waiting("filtering"), created_at: "2026-10-27T10:00:00Z" }])?.status,
    ).toBe("waiting");
    expect(stopOf({ ...SESSION, status: "running", stage: "filtering" })).toBeNull();
  });
});

it("takes the stop from what Next step would start, before the stage", () => {
  const waiting = { ...SESSION, status: "waiting" as const };
  expect(stopOf({ ...waiting, stage: "classifying", next_step: "check" })).toBe("changes");
  expect(stopOf({ ...waiting, stage: "filtering", next_step: "propose" })).toBe("understand");
  expect(stopOf({ ...waiting, stage: "filtering", next_step: null })).toBe("changes");
});
