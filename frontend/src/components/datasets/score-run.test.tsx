import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import type { CaseScore, DatasetScoring } from "@/types/scoring";
import { ScoreRunButton } from "./score-run-button";

type Kase = {
  case_id: string;
  input: string;
  reference_answer?: string | null;
  checks?: { type: string }[];
};

const state = vi.hoisted(() => ({
  datasets: [] as { id: string; name: string; scoring?: DatasetScoring }[],
  datasetTotal: null as number | null,
  datasetsError: null as Error | null,
  refetchDatasets: vi.fn(),
  isLoading: false,
  cases: {} as Record<string, Kase[]>,
  caseTotal: null as number | null,
  casesError: null as Error | null,
  refetchCases: vi.fn(),
  caseCalls: [] as { datasetId: string; skip?: number }[],
  searches: [] as string[],
  score: vi.fn(),
  pending: false,
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: ({ search }: { search: string }) => {
    state.searches.push(search);
    return {
      datasets: state.datasets,
      total: state.datasetTotal ?? state.datasets.length,
      isLoading: state.isLoading,
      error: state.datasetsError,
      refetch: state.refetchDatasets,
    };
  },
  useDatasetCases: (datasetId: string, { skip }: { skip?: number } = {}) => {
    state.caseCalls.push({ datasetId, skip });
    const cases = (state.cases[datasetId] ?? []).map((item) => ({
      reference_answer: null,
      checks: [],
      ...item,
    }));
    return {
      cases,
      total: state.caseTotal ?? cases.length,
      error: state.casesError,
      refetch: state.refetchCases,
    };
  },
}));
vi.mock("@/hooks/use-scoring", () => ({
  useScoreRun: () => ({ mutateAsync: state.score, isPending: state.pending }),
}));

const SCORE: CaseScore = {
  id: "s1",
  dataset_id: "d1",
  case_id: "c1",
  case_revision_id: "r1",
  question: "How long is the refund window?",
  reference_answer: null,
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
  state.datasetTotal = null;
  state.datasetsError = null;
  state.caseTotal = null;
  state.casesError = null;
  state.caseCalls = [];
  state.searches = [];
  state.cases = {
    d1: [{ case_id: "c1", input: "How long is the refund window?" }],
    d2: [{ case_id: "c2", input: "x".repeat(100), reference_answer: "Thirty days." }],
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

  it("says which scorers will run, and that the judge's half is a paid run", async () => {
    state.datasets = [
      { id: "d1", name: "refunds", scoring: DEFAULT_SCORING },
      {
        id: "d2",
        name: "returns",
        scoring: { ...DEFAULT_SCORING, reference: { enabled: true, required: true } },
      },
    ];
    render(<ScoreRunButton runId="run-1" />);

    await open();
    expect(screen.getByText("Runs Checks and Tool calls.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));

    expect(
      screen.getByText(
        "Runs Checks, Tool calls, and Reference answer. The judge's grading is a run of the eval judge, charged to its budget.",
      ),
    ).toBeInTheDocument();
  });

  it("warns of the judge's cost when only the case's own judge check calls it", async () => {
    state.datasets = [{ id: "d1", name: "refunds", scoring: DEFAULT_SCORING }];
    state.cases = { d1: [{ case_id: "c1", input: "Polite?", checks: [{ type: "judge" }] }] };
    render(<ScoreRunButton runId="run-1" />);

    await open();

    expect(screen.getByText(/charged to its budget/)).toBeInTheDocument();
  });

  it("offers a retry when the datasets could not be read, rather than saying there are none", async () => {
    state.datasets = [];
    state.datasetsError = new Error("502");
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(state.refetchDatasets).toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Create one" })).toBeNull();
  });

  it("searches the datasets once there are more than one listing holds", async () => {
    state.datasetTotal = 250;
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "ref");

    await waitFor(() => expect(state.searches).toContain("ref"));
  });

  it("pages through a dataset with more cases than one listing holds", async () => {
    state.caseTotal = 250;
    render(<ScoreRunButton runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    expect(state.caseCalls.at(-1)).toEqual({ datasetId: "d1", skip: 100 });
  });

  it("says why the cases could not be read", async () => {
    state.casesError = new Error("Cases unavailable");
    render(<ScoreRunButton runId="run-1" />);

    await open();

    expect(screen.getByText("Cases unavailable")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetchCases).toHaveBeenCalled();
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
