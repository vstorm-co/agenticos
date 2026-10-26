import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import {
  currentImprovementStep,
  improvementStepStates,
  isClosed,
  openImprovement,
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
  expect(states.testSet).toBe("done");
  expect(states.today).toBe("pending");
  expect(states.changes).toBe("pending");
});
it("shows the current check running even if an earlier round was measured", () => {
  const states = improvementStepStates({ ...SESSION, status: "running", stage: "evaluating" });
  expect(states.check).toBe("running");
  expect(states.today).toBe("done");
  expect(states.changes).toBe("done");
});
it("asks for one decision at a time: the result first, then acceptance", () => {
  const states = improvementStepStates({ ...SESSION, status: "ready", stage: "judging" });
  expect(Object.values(states).filter((state) => state === "needs_you")).toHaveLength(1);
  expect(states).toMatchObject({ changes: "done", result: "needs_you", accept: "pending" });
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
      today: "skipped",
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
  ).toMatchObject({ understand: "needs_you", testSet: "needs_you", today: "skipped" });
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
  ).toMatchObject({ changes: "needs_you", check: "skipped", today: "skipped", understand: "done" });
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
