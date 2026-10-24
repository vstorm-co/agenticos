import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { attempt, evalCase } from "@/test-utils/eval-runs";
import { ChangedAnswers } from "./changed-answers";
const state = vi.hoisted(() => ({ error: null as Error | null, loading: false }));
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
  useEvalComparison: () => ({ comparison: { cases: [{ case_id: "case-1", flip: "fixed" }] } }),
}));
beforeEach(() => {
  state.error = null;
  state.loading = false;
});
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
