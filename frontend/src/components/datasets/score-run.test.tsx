import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseScore } from "@/types/scoring";
import { ScoreRunButton } from "./score-run-button";

const state = vi.hoisted(() => ({
  datasets: [] as { id: string; name: string }[],
  isLoading: false,
  cases: {} as Record<string, { case_id: string; input: string }[]>,
  score: vi.fn(),
  pending: false,
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: () => ({ datasets: state.datasets, isLoading: state.isLoading }),
  useDatasetCases: (datasetId: string) => ({ cases: state.cases[datasetId] ?? [] }),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useScoreRun: () => ({ mutateAsync: state.score, isPending: state.pending }),
}));

const SCORE: CaseScore = {
  id: "s1",
  dataset_id: "d1",
  case_id: "c1",
  case_revision_id: "r1",
  run_id: "run-1",
  judge: null,
  results: [
    {
      scorer: "check",
      name: "json_schema",
      required: true,
      status: "pass",
      score: 1,
      reason: "Matches the schema",
      reason_code: null,
      judge_run_id: null,
    },
  ],
  passed: true,
  review_state: "none",
  human_passed: null,
  human_note: null,
  reviewed_by_user_id: null,
  reviewed_at: null,
  created_by_user_id: null,
  created_at: "2026-10-13T00:00:00Z",
  outcome: true,
};

const open = () => userEvent.click(screen.getByRole("button", { name: "Score against a case" }));

beforeEach(() => {
  vi.clearAllMocks();
  state.datasets = [
    { id: "d1", name: "refunds" },
    { id: "d2", name: "returns" },
  ];
  state.isLoading = false;
  state.pending = false;
  state.cases = {
    d1: [{ case_id: "c1", input: "How long is the refund window?" }],
    d2: [{ case_id: "c2", input: "x".repeat(100) }],
  };
});

/** Scoring a run from Activity: pick the case, see what each scorer said. */
describe("Score against a case", () => {
  it("scores the run against the first case and shows each scorer's reason", async () => {
    state.score.mockResolvedValue(SCORE);
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() => expect(screen.getByText("Matches the schema")).toBeInTheDocument());
    expect(state.score).toHaveBeenCalledWith({ datasetId: "d1", caseId: "c1", runId: "run-1" });
    // The footer's and the dialog's own close both answer to the name.
    await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    expect(screen.queryByText("Matches the schema")).toBeNull();
  });

  it("takes the case from the dataset chosen, shortening a long question", async () => {
    state.score.mockResolvedValue(SCORE);
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Case" }));
    await userEvent.click(screen.getByRole("option", { name: `${"x".repeat(80)}…` }));
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() =>
      expect(state.score).toHaveBeenCalledWith({ datasetId: "d2", caseId: "c2", runId: "run-1" }),
    );
  });

  it("says why the score was refused and keeps the choice", async () => {
    state.score.mockRejectedValue(new Error("This run kept no answer to score"));
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    expect(await screen.findByText("This run kept no answer to score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Score" })).toBeInTheDocument();
  });

  it("points at Datasets when there is nothing to score against", async () => {
    state.datasets = [];
    render(<ScoreRunButton runId="run-1" />);

    await open();

    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/datasets");
    expect(screen.getByRole("button", { name: "Score" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("shows that it is scoring while the judge runs", async () => {
    state.pending = true;
    render(<ScoreRunButton runId="run-1" />);

    await open();

    expect(screen.getByRole("button", { name: "Scoring…" })).toBeDisabled();
  });
});
