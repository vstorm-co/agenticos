import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import { caseScore } from "@/test-utils/scores";
import type { DatasetScoring } from "@/types/scoring";

import { JudgeDatasetsCard } from "./judge-datasets-card";

const state = vi.hoisted(() => ({
  result: {
    datasets: [] as { id: string; name: string; scoring: DatasetScoring }[],
    isLoading: false,
    error: null as Error | null,
  },
}));
vi.mock("@/hooks/use-datasets", () => ({ useDatasets: () => state.result }));
const agreement = vi.hoisted(() => ({
  value: undefined as { agreed: number; decided: number } | undefined,
}));
const grades = vi.hoisted(() => ({
  result: { scores: [] as unknown[], isLoading: false, error: null as Error | null },
  asked: [] as unknown[],
}));
vi.mock("@/components/evals/eval-run-verdict", () => ({
  EvalRunVerdict: ({ runId }: { runId: string }) => <span>verdict of {runId}</span>,
}));
vi.mock("@/hooks/use-scoring", () => ({
  useJudgeAgreement: () => ({ agreement: agreement.value, isLoading: false }),
  useScores: (...args: unknown[]) => {
    grades.asked.push(args);
    return grades.result;
  },
}));

const GRADING: DatasetScoring = {
  ...DEFAULT_SCORING,
  judge: { ...DEFAULT_SCORING.judge, enabled: true },
};

beforeEach(() => {
  state.result = { datasets: [], isLoading: false, error: null };
  agreement.value = undefined;
  grades.result = { scores: [], isLoading: false, error: null };
  grades.asked = [];
});

describe("JudgeDatasetsCard", () => {
  it("links each dataset of the judge to its Grading tab, and says which grade nothing", () => {
    state.result.datasets = [
      { id: "d1", name: "Refunds", scoring: GRADING },
      { id: "d2", name: "Golden", scoring: DEFAULT_SCORING },
    ];
    render(<JudgeDatasetsCard judgeId="j1" />);

    expect(screen.getByRole("link", { name: "Refunds" })).toHaveAttribute(
      "href",
      "/datasets/d1?tab=grading",
    );
    const golden = screen.getByRole("link", { name: "Golden" }).closest("li")!;
    expect(within(golden).getByText("Grading off")).toBeInTheDocument();
    expect(screen.getAllByText("Grading off")).toHaveLength(1);
  });

  it("opens a dataset on what the judge graded there, and its eval runs", async () => {
    state.result.datasets = [{ id: "d1", name: "Refunds", scoring: GRADING }];
    grades.result.scores = [
      caseScore({
        id: "s1",
        question: "Can I return a gift code?",
        outcome: false,
        run_id: "r1",
        eval_run_id: "e1",
        agent_id: "a1",
      }),
      caseScore({
        id: "s2",
        question: "Where is my order?",
        outcome: null,
        eval_run_id: "e1",
        agent_id: "a1",
      }),
      caseScore({ id: "s3", question: "Refund window?", outcome: true, run_id: null }),
    ];
    render(<JudgeDatasetsCard judgeId="j1" />);
    expect(grades.asked).toEqual([]);

    await userEvent.click(
      screen.getByRole("button", { name: "Show what this judge graded in Refunds" }),
    );

    expect(grades.asked.at(-1)).toEqual(["d1", { judgeId: "j1", limit: 5 }]);
    const latest = screen.getByRole("list", { name: "Its latest grades" });
    expect(within(latest).getAllByRole("listitem")).toHaveLength(3);
    expect(within(latest).getByText("Failed")).toBeInTheDocument();
    expect(within(latest).getByText("Not graded")).toBeInTheDocument();
    expect(within(latest).getByText("Passed")).toBeInTheDocument();
    expect(within(latest).getAllByRole("link", { name: "Answer ↗" })).toHaveLength(1);
    expect(within(latest).getByRole("link", { name: "Answer ↗" })).toHaveAttribute(
      "href",
      "/runs?run=r1",
    );
    const runs = screen.getByRole("list", { name: "Eval runs it graded" });
    expect(within(runs).getByRole("link")).toHaveAttribute("href", "/agents/a1/evals/e1");
    expect(within(runs).getByText("verdict of e1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all on the Review tab" })).toHaveAttribute(
      "href",
      "/datasets/d1?tab=review",
    );
  });

  it("says what an opened dataset holds of the judge's grades when it has none, or none to read", async () => {
    state.result.datasets = [{ id: "d1", name: "Refunds", scoring: GRADING }];
    const { rerender } = render(<JudgeDatasetsCard judgeId="j1" />);
    await userEvent.click(
      screen.getByRole("button", { name: "Show what this judge graded in Refunds" }),
    );
    expect(
      screen.getByText("This judge has graded nothing in this dataset yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Eval runs it graded" })).toBeNull();

    grades.result = { scores: [], isLoading: false, error: new Error("Scores are unreachable") };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.getByText("Scores are unreachable")).toBeInTheDocument();

    grades.result = { scores: [], isLoading: true, error: null };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.queryByText("This judge has graded nothing in this dataset yet.")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: "Show what this judge graded in Refunds" }),
    );
    expect(screen.queryByText("Scores are unreachable")).toBeNull();
  });

  it("says when no dataset uses the judge", () => {
    render(<JudgeDatasetsCard judgeId="j1" />);

    expect(screen.getByText("No dataset uses this judge yet.")).toBeInTheDocument();
  });

  it("says why the datasets could not be read, and waits while they load", () => {
    state.result.error = new Error("Datasets are unreachable");
    const { rerender } = render(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.getByText("Datasets are unreachable")).toBeInTheDocument();

    state.result = { datasets: [], isLoading: true, error: null };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.queryByText("No dataset uses this judge yet.")).toBeNull();
  });

  it("says how often people agreed with the judge, once anybody decided", () => {
    const { rerender } = render(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.queryByText(/agreed with this judge/)).toBeNull();

    agreement.value = { agreed: 0, decided: 0 };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.getByText(/Nobody has decided a result this judge graded/)).toBeInTheDocument();

    agreement.value = { agreed: 7, decided: 10 };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(
      screen.getByText("People agreed with this judge on 7 of 10 results they decided."),
    ).toBeInTheDocument();
  });
});
