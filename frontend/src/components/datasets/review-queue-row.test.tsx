import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { caseScore } from "@/test-utils/scores";
import { evalRun } from "@/test-utils/eval-runs";
import { evalSuite, suiteResult, suiteSummary } from "@/test-utils/eval-suites";
import { ReviewQueueRow } from "./review-queue-row";

const state = vi.hoisted(() => ({
  error: false,
  loading: false,
  undo: false,
  noComparison: false,
  failed: false,
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({
    error: state.error ? new Error("forbidden") : null,
    run: state.loading
      ? null
      : evalRun({
          status: state.failed ? "failed" : "completed",
          review: {
            by_user_id: "u1",
            by_name: state.undo ? null : "Ada",
            at: "2026-10-24T12:00:00Z",
            undo: state.undo,
            previous_verdict: "worse",
            verdict: "better",
          },
          outcome: state.noComparison
            ? null
            : {
                candidate_arm_id: "arm-1",
                candidate_crashed: 0,
                verdict: "better",
                overall: "better",
                baseline: null,
                regressions_confirmed: 0,
                fixed_confirmed: 1,
                candidate_pass_rate: 1,
                baseline_pass_rate: 0,
                candidate_first_pass_rate: 1,
                baseline_first_pass_rate: 0,
                candidate_undecided: 0,
              },
        }),
  }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useAgentEvalSuites: () => ({
    suites: [
      evalSuite({
        name: "Refund smoke",
        last_result: suiteResult({ eval_run_id: "r1", summary: suiteSummary() }),
      }),
      evalSuite({
        id: "unrelated",
        name: "Other run",
        last_result: suiteResult({ eval_run_id: "r2" }),
      }),
    ],
  }),
}));
beforeEach(() => {
  state.error = false;
  state.loading = false;
  state.undo = false;
  state.noComparison = false;
  state.failed = false;
});

const score = caseScore({
  agent_id: "a1",
  eval_run_id: "r1",
  human_passed: true,
  human_note: "Use policy",
  outcome: true,
});
it("keeps the corrected run and suite results beside the decided answer", async () => {
  render(<ReviewQueueRow score={score} busy={false} linksRuns />);
  await userEvent.click(screen.getByRole("button", { name: score.question }));
  expect(screen.getByText(/Re-evaluated after review by Ada/)).toBeInTheDocument();
  expect(screen.getByText("Run: better")).toBeInTheDocument();
  expect(screen.getByText("Refund smoke: Passed after review")).toBeInTheDocument();
  expect(screen.queryByText(/Other run/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: score.question })).toBeInTheDocument();
});
it("explains a missing run and never replaces a failure with a successful result", async () => {
  state.error = true;
  const { rerender } = render(<ReviewQueueRow score={score} busy={false} linksRuns />);
  await userEvent.click(screen.getByRole("button", { name: score.question }));
  expect(screen.getByText(/updated run could not be read/)).toBeInTheDocument();
  expect(screen.queryByText("Run: better")).not.toBeInTheDocument();
  state.error = false;
  state.loading = true;
  rerender(<ReviewQueueRow score={score} busy={false} linksRuns />);
  expect(screen.getByText("Refreshing the result…")).toBeInTheDocument();
});
it("labels an undone review without revealing an identity that no longer resolves", async () => {
  state.undo = true;
  render(<ReviewQueueRow score={score} busy={false} linksRuns />);
  await userEvent.click(screen.getByRole("button", { name: score.question }));
  expect(
    screen.getByText(/Re-evaluated after review was undone by a reviewer/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Ada/)).not.toBeInTheDocument();
});

it("distinguishes a completed unpaired run from a run that did not finish", async () => {
  state.noComparison = true;
  const { rerender } = render(<ReviewQueueRow score={score} busy={false} linksRuns />);
  await userEvent.click(screen.getByRole("button", { name: score.question }));
  expect(screen.getByText("Run: no baseline comparison was requested.")).toBeInTheDocument();
  state.failed = true;
  rerender(<ReviewQueueRow score={score} busy={false} linksRuns />);
  expect(
    screen.getByText("The run did not complete. Open its check for the reason."),
  ).toBeInTheDocument();
  expect(screen.queryByText("Refreshing the result…")).not.toBeInTheDocument();
});
it("says where an answer came from in its card, the table's source column saying it closed", async () => {
  render(<ReviewQueueRow score={{ ...score, human_passed: null }} busy={false} linksRuns />);
  expect(screen.queryByText("Eval run")).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: score.question }));

  expect(screen.getAllByText("Eval run")).toHaveLength(1);
});
