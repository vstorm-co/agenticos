import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { attempt, evalCase } from "@/test-utils/eval-runs";
import { ChangedAnswers } from "./changed-answers";
const state = vi.hoisted(() => ({
  error: null as Error | null,
  loading: false,
  status: "completed",
  confirmed: true,
  invalid: false,
}));
const comparisonOptions = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalCases: () => ({
    error: state.error,
    isLoading: state.loading,
    cases: [
      evalCase({
        input: "How long can I return an order?",
        attempts: [
          attempt({ arm_id: "before", answer: "90 days" }),
          attempt({ arm_id: "after", answer: "30 days" }),
        ],
      }),
    ],
  }),
  useEvalRun: () => ({ run: { status: state.status } }),
  useEvalComparison: (_id: string, options: { live: boolean }) => {
    comparisonOptions(options);
    return {
      comparison: {
        verdict: state.invalid ? "invalid" : "better",
        cases: [{ case_id: "case-1", flip: "fixed", confirmed: state.confirmed }],
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
        caseIds={["case-1"]}
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
      caseIds={["case-1"]}
      baselineId="before"
      candidateId="after"
      attributions={{ h1: "attribution-1" }}
    />,
  );
  expect(screen.getByText("90 days")).toBeInTheDocument();
  expect(screen.getByText("30 days")).toBeInTheDocument();
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
      caseIds={["case-1"]}
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
      caseIds={["case-1"]}
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
    caseIds: ["case-1"],
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
