import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { caseScore } from "@/test-utils/scores";
import { attempt, evalCase, FLIP } from "@/test-utils/eval-runs";
import { ChangedAnswers } from "./changed-answers";
const state = vi.hoisted(() => ({
  error: null as Error | null,
  loading: false,
  status: "completed",
  confirmed: true,
  invalid: false,
  comparisonAvailable: true,
  missingAnswers: false,
  flip: "fixed" as "fixed" | "regression" | "unchanged",
}));
const comparisonOptions = vi.hoisted(() => vi.fn());
const FLIPS = [{ ...FLIP, case_id: "case-1", flip: "fixed" as const, confirmed: true }];
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalCases: () => ({
    error: state.error,
    isLoading: state.loading,
    cases: [
      evalCase({
        input: "How long can I return an order?",
        attempts: [
          attempt({ arm_id: "before", answer: state.missingAnswers ? null : "90 days" }),
          attempt({
            arm_id: "after",
            answer: state.missingAnswers ? null : "30 days",
            score: caseScore({
              results: [
                {
                  scorer: "check",
                  name: "Return policy",
                  required: true,
                  status: "pass",
                  score: 1,
                  reason_code: null,
                  unverified_quotes: [],
                  rule: null,
                  unverified: false,
                  judge_said: null,
                  judge_run_id: null,
                  knowledge: [],
                  reason: "Matches the reviewed return policy",
                },
              ],
            }),
          }),
        ],
      }),
    ],
  }),
  useEvalRun: () => ({ run: { status: state.status } }),
  useEvalComparison: (_id: string, options: { live: boolean }) => {
    comparisonOptions(options);
    return {
      comparison: !state.comparisonAvailable
        ? null
        : {
            verdict: state.invalid ? "invalid" : "better",
            cases: [{ case_id: "case-1", flip: state.flip, confirmed: state.confirmed }],
          },
    };
  },
}));
beforeEach(() => {
  state.error = null;
  state.loading = false;
  state.status = "completed";
  state.confirmed = true;
  state.invalid = false;
  state.comparisonAvailable = true;
  state.missingAnswers = false;
  state.flip = "fixed";
  comparisonOptions.mockClear();
});
it.each(["failed", "cancelled", "budget_exceeded"])(
  "does not keep polling a %s attribution",
  (status) => {
    state.status = status;
    render(
      <ChangedAnswers
        runId="r1"
        agentId="a1"
        flips={FLIPS}
        baselineId="before"
        candidateId="after"
        attributions={{ h1: "attribution-1" }}
      />,
    );
    expect(screen.getByText("The check of change 1 could not be read.")).toBeInTheDocument();
    expect(comparisonOptions).toHaveBeenLastCalledWith({ live: false });
    expect(screen.queryByText("Change 1: newly fixed")).not.toBeInTheDocument();
  },
);
it("shows changed answers beside their separate attribution result", () => {
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{ h1: "attribution-1" }}
    />,
  );
  expect(screen.getByText("90 days")).toBeInTheDocument();
  expect(screen.getByText("30 days")).toBeInTheDocument();
  expect(screen.getByText("Grader: Matches the reviewed return policy")).toBeInTheDocument();
  expect(screen.getByText("Change 1: newly fixed")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the full check" })).toHaveAttribute(
    "href",
    "/agents/a1/evals/r1",
  );
});
it("does not claim attribution before it has been requested", () => {
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{}}
    />,
  );
  expect(screen.getByText(/Not tested separately/)).toBeInTheDocument();
});
it("shows an unavailable result instead of an empty successful comparison", () => {
  state.error = new Error("unavailable");
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{}}
    />,
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("30 days")).not.toBeInTheDocument();
});

it("does not attribute an unconfirmed flip or an invalid comparison", () => {
  state.confirmed = false;
  const props = {
    runId: "r1",
    agentId: "a1",
    flips: FLIPS,
    baselineId: "before",
    candidateId: "after",
    attributions: { h1: "attr" },
  };
  const view = render(<ChangedAnswers {...props} />);
  expect(screen.getByText("Change 1: the result is not confirmed.")).toBeInTheDocument();
  expect(screen.queryByText("Change 1: newly fixed")).not.toBeInTheDocument();
  state.invalid = true;
  view.rerender(<ChangedAnswers {...props} />);
  expect(screen.getByText("The check of change 1 could not be read.")).toBeInTheDocument();
});

it("shows progress while the answer rows are loading", () => {
  state.loading = true;
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{}}
    />,
  );
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText("30 days")).not.toBeInTheDocument();
});

it.each([
  ["regression", "Change 1: newly broken"],
  ["unchanged", "Change 1: no measured change for this question"],
] as const)("distinguishes a confirmed %s from a fix", (flip, text) => {
  state.flip = flip;
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{ h1: "attr" }}
    />,
  );
  expect(screen.getByText(text)).toBeInTheDocument();
});
it("keeps an unfinished attribution and unavailable answers explicit", () => {
  state.comparisonAvailable = false;
  state.missingAnswers = true;
  render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={FLIPS}
      baselineId="before"
      candidateId="after"
      attributions={{ h1: "attr" }}
    />,
  );
  expect(screen.getByText("Still checking change 1…")).toBeInTheDocument();
  expect(screen.queryByText("30 days")).not.toBeInTheDocument();
});

it("marks each row newly fixed or newly broken and keeps unconfirmed ones apart", () => {
  const view = render(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={[{ ...FLIPS[0]!, flip: "regression" }]}
      baselineId="before"
      candidateId="after"
      attributions={{}}
    />,
  );
  expect(screen.getByText("Newly broken")).toBeInTheDocument();
  expect(screen.queryByText(/Not confirmed yet/)).not.toBeInTheDocument();
  view.rerender(
    <ChangedAnswers
      runId="r1"
      agentId="a1"
      flips={[{ ...FLIPS[0]!, confirmed: false }]}
      baselineId="before"
      candidateId="after"
      attributions={{}}
    />,
  );
  const group = screen.getByText("Not confirmed yet (1)").closest("details")!;
  expect(group).not.toHaveAttribute("open");
  expect(group).toHaveTextContent("Newly fixed");
});
