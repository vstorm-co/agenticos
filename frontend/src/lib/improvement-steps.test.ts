import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import { currentImprovementStep, improvementStepStates } from "./improvement-steps";

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
it("requires human review of prepared changes and the final decision", () => {
  const states = improvementStepStates({ ...SESSION, status: "ready", stage: "judging" });
  expect(states.changes).toBe("needs_you");
  expect(states.result).toBe("needs_you");
  expect(states.accept).toBe("needs_you");
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
