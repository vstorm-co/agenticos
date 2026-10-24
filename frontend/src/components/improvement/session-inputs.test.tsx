import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { arm, attempt, evalCase, evalRun, SUMMARY } from "@/test-utils/eval-runs";
import { caseScore } from "@/test-utils/scores";
import { SESSION } from "@/test-utils/improvement";
import type { EvalRun, EvalCase } from "@/types/eval-runs";
import type { ImprovementEvidence } from "@/types/improvement";
import { StartSignals, Understand, TestQuestions, Today } from "./session-inputs";
const state = vi.hoisted(() => ({
  sources: null as ImprovementEvidence | null,
  sourceError: null as Error | null,
  loading: false,
  attentionError: null as Error | null,
  rated: 5,
  total: 21,
  questions: [
    {
      id: "q1",
      input: "Return window?",
      improvement_partition: "train",
      reference_answer: "30 days",
    },
    { id: "q2", input: "Shipping?", improvement_partition: "holdout", reference_answer: null },
  ],
  questionError: null as Error | null,
  evalError: null as Error | null,
  run: null as EvalRun | null,
  cases: [] as EvalCase[],
  casesError: null as Error | null,
  casesLoading: false,
  datasetHook: vi.fn(),
  evidenceHook: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovementEvidence: (...args: unknown[]) => {
    state.evidenceHook(...args);
    return { evidence: state.sources, isLoading: state.loading, error: state.sourceError };
  },
}));
vi.mock("@/hooks/use-usage-stats", () => ({
  useAgentAttention: () => ({
    agents: state.rated ? [{ agent_id: "a1", rated_down: state.rated, failed_runs: 2 }] : [],
    isLoading: state.loading,
    error: state.attentionError,
  }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasetCases: (...args: unknown[]) => {
    state.datasetHook(...args);
    return {
      cases: state.questions,
      total: state.total,
      isLoading: state.loading,
      error: state.questionError,
    };
  },
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({ run: state.run, error: state.evalError }),
  useEvalCases: () => ({
    cases: state.cases,
    isLoading: state.casesLoading,
    error: state.casesError,
  }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.sources = {
    sample_limit: 20,
    training_failures: 3,
    items: [
      {
        run_id: "r1",
        conversation_id: "c1",
        kind: "chat",
        status: "completed",
        rating: -1,
        question: "Refund?",
        answer: "90 days",
        comments: ["Wrong policy"],
        branch: "unknown",
        reason: null,
      },
      {
        run_id: "r2",
        conversation_id: null,
        kind: "train_eval",
        status: "train_eval_failure",
        rating: 0,
        question: "Deadline?",
        answer: null,
        comments: [],
        branch: "agent",
        reason: null,
      },
      {
        run_id: "r3",
        conversation_id: null,
        kind: "chat",
        status: "completed",
        rating: -1,
        question: "Shipping fee?",
        answer: "Unknown",
        comments: [],
        branch: "missing_knowledge",
        reason: "No source passage",
      },
      {
        run_id: "r4",
        conversation_id: "c2",
        kind: "chat",
        status: "completed",
        rating: 1,
        question: null,
        answer: null,
        comments: [],
        branch: "not_a_problem",
        reason: null,
      },
    ],
  };
  state.sourceError =
    state.attentionError =
    state.questionError =
    state.evalError =
    state.casesError =
      null;
  state.loading = state.casesLoading = false;
  state.rated = 5;
  state.total = 21;
  state.questions = [
    {
      id: "q1",
      input: "Return window?",
      improvement_partition: "train",
      reference_answer: "30 days",
    },
    { id: "q2", input: "Shipping?", improvement_partition: "holdout", reference_answer: null },
  ];
  state.run = evalRun({
    agent_id: "a1",
    arms: [
      arm({ id: "base", role: "baseline", summary: { ...SUMMARY, incomplete: 1, ungraded: 2 } }),
    ],
  });
  state.cases = [evalCase({ attempts: [attempt({ arm_id: "base", answer: "90 days" })] })];
});
it("shows real signal counts and labels the bounded training sample", () => {
  render(<StartSignals agentId="a1" datasetId="d1" />);
  for (const count of ["5", "2", "3"]) expect(screen.getByText(count)).toBeInTheDocument();
  expect(state.evidenceHook).toHaveBeenCalledWith("a1", { datasetId: "d1" });
});
it("distinguishes loading, read failures and no learning data", () => {
  state.loading = true;
  const view = render(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.sourceError = new Error("Cannot load sources");
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.sourceError = null;
  state.attentionError = new Error("Cannot read counts");
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.attentionError = null;
  state.rated = 0;
  state.sources = { items: [], sample_limit: 20, training_failures: 0 };
  view.rerender(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getAllByText("0")).toHaveLength(3);
  expect(screen.getByText(/Nothing to learn from yet/)).toBeInTheDocument();
});
it("keeps unknown causes explicit and shows quotes, comments, reasons and source links", async () => {
  render(<Understand session={SESSION} />);
  expect(screen.getByText(/no recorded cause/)).toBeInTheDocument();
  expect(screen.getByText("Wrong policy")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Open conversation" })[0]).toHaveAttribute(
    "href",
    "/chat/c1",
  );
  await userEvent.click(screen.getAllByText("Why we think so")[0]!);
  expect(screen.getByText(/has not been classified/)).toBeInTheDocument();
  expect(screen.getByText("No source passage")).toBeInTheDocument();
  expect(screen.getByText(/training answer failed/)).toBeInTheDocument();
  await userEvent.click(screen.getByText(/Not a problem to fix/));
  expect(screen.getByText(/existing feedback and classification/)).toBeInTheDocument();
});
it("does not invent examples when sources are gone or unreadable", () => {
  state.sources = { items: [], sample_limit: 20, training_failures: 0 };
  const view = render(<Understand session={SESSION} />);
  expect(screen.getByText(/Nothing to learn from yet/)).toBeInTheDocument();
  expect(screen.getAllByText(/No selected examples/)).toHaveLength(2);
  state.loading = true;
  view.rerender(<Understand session={{ ...SESSION, status: "running" }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.sourceError = new Error("Forbidden");
  view.rerender(<Understand session={SESSION} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.sourceError = null;
  state.sources = null;
  view.rerender(<Understand session={{ ...SESSION, status: "queued" }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
});
it("pages the pinned questions and explains train versus holdout", async () => {
  render(<TestQuestions session={SESSION} />);
  expect(state.datasetHook).toHaveBeenLastCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 0,
    limit: 20,
  });
  await userEvent.click(screen.getByText("Review the questions"));
  expect(screen.getByText("A good answer: 30 days")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous questions" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Next questions" }));
  expect(state.datasetHook).toHaveBeenLastCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 20,
    limit: 20,
  });
  expect(screen.getByRole("button", { name: "Next questions" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Previous questions" }));
  expect(state.datasetHook).toHaveBeenLastCalledWith(SESSION.dataset_id, {
    version: SESSION.dataset_version,
    skip: 0,
    limit: 20,
  });
});
it("explains missing questions and handles their loading or access failure", () => {
  state.total = 0;
  state.questions = [];
  const view = render(<TestQuestions session={SESSION} />);
  expect(screen.getByText(/no questions in this pinned version/)).toBeInTheDocument();
  state.loading = true;
  view.rerender(<TestQuestions session={SESSION} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.loading = false;
  state.questionError = new Error("Forbidden");
  view.rerender(<TestQuestions session={SESSION} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("shows the actual baseline and keeps ungraded questions separate", () => {
  render(<Today session={SESSION} />);
  expect(screen.getByText("Before the changes: 3 of 4 handled well.")).toBeInTheDocument();
  expect(screen.getByText(/Could not grade 3 questions/)).toBeInTheDocument();
  expect(screen.getByText("90 days")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open the full check" })).toHaveAttribute(
    "href",
    `/agents/a1/evals/${SESSION.iterations[0]!.eval_run_ids[0]}`,
  );
});
it("does not fetch a nonexistent baseline and handles absent or inaccessible arms", () => {
  const view = render(<Today session={{ ...SESSION, iterations: [] }} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.run = null;
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.run = evalRun();
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.evalError = new Error("Forbidden");
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
});
it("shows weak-answer loading and failures rather than a false clean result", () => {
  state.casesLoading = true;
  const view = render(<Today session={SESSION} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.casesLoading = false;
  state.casesError = new Error("Unavailable");
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
  state.casesError = null;
  state.cases = [];
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByText(/No failed questions on this page/)).toBeInTheDocument();
});

it.each(["queued", "running", "failed", "cancelled"] as const)(
  "does not report a partial %s baseline as a measurement",
  (status) => {
    state.run = evalRun({ status, arms: [arm({ role: "baseline" })] });
    render(<Today session={SESSION} />);
    expect(screen.queryByText(/Before the changes:/)).not.toBeInTheDocument();
    expect(
      screen.getByRole(status === "queued" || status === "running" ? "status" : "alert"),
    ).toBeInTheDocument();
  },
);

it("shows the grader reason and handles a missing persisted baseline answer", () => {
  state.cases = [
    evalCase({
      attempts: [
        attempt({
          arm_id: "base",
          score: caseScore({
            results: [
              {
                scorer: "check",
                required: true,
                score: 0,
                reason_code: null,
                unverified_quotes: [],
                rule: null,
                unverified: false,
                judge_said: null,
                judge_run_id: null,
                name: "return window",
                status: "fail",
                reason: "The answer uses the old deadline",
              },
            ],
          }),
        }),
      ],
    }),
  ];
  const view = render(<Today session={SESSION} />);
  expect(screen.getByText("The answer uses the old deadline")).toBeInTheDocument();
  state.cases = [evalCase({ attempts: [] })];
  view.rerender(<Today session={SESSION} />);
  expect(screen.getByText("No answer is available.")).toBeInTheDocument();
});
it("waits for source counts instead of printing a missing response as zero", () => {
  state.sources = null;
  render(<StartSignals agentId="a1" datasetId="" />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});
