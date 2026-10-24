import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { caseScore } from "@/test-utils/scores";

import { DEFAULT_SCORING } from "@/lib/scoring";
import type { CaseScore, DatasetScoring } from "@/types/scoring";
import { RunMoreMenu } from "@/components/runs/run-more-menu";

type Kase = {
  case_id: string;
  input: string;
  reference_answer?: string | null;
  checks?: { type: string }[];
};

const state = vi.hoisted(() => ({
  datasets: [] as {
    id: string;
    name: string;
    can_run?: boolean;
    scoring?: DatasetScoring;
    judge_name?: string | null;
  }[],
  judges: [] as {
    id: string;
    name: string;
    system_key: string | null;
    published_model?: { label: string } | null;
  }[],
  datasetTotal: null as number | null,
  datasetsError: null as Error | null,
  refetchDatasets: vi.fn(),
  isLoading: false,
  cases: {} as Record<string, Kase[]>,
  caseTotal: null as number | null,
  casesError: null as Error | null,
  casesLoading: false,
  refetchCases: vi.fn(),
  caseCalls: [] as { datasetId: string; skip?: number }[],
  searches: [] as string[],
  // The datasets the server says have a case asking the run's question, and the runs it was asked about.
  holding: [] as { id: string; name: string; can_run?: boolean }[],
  holdingLoading: false,
  asked: [] as string[],
  score: vi.fn(),
  pending: false,
  turns: [] as { id: string; role: string; content: string }[] | null,
  transcriptOptions: undefined as { tail?: boolean } | undefined,
}));
vi.mock("@/hooks/use-runs", () => ({
  useRunTranscript: (_runId: string, _scope: string, options?: { tail?: boolean }) => {
    state.transcriptOptions = options;
    return { transcript: state.turns === null ? undefined : { items: state.turns } };
  },
}));
vi.mock("./add-to-dataset-dialog", () => ({
  AddToDatasetDialog: ({ messageId }: { messageId: string }) => (
    <div role="dialog" aria-label="Add to dataset">
      {messageId}
    </div>
  ),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: ({ search, asksRun }: { search?: string; asksRun?: string }) => {
    if (asksRun !== undefined) {
      state.asked.push(asksRun);
      return {
        datasets: state.holding.map((item) => ({ can_run: true, ...item })),
        isLoading: state.holdingLoading,
      };
    }
    state.searches.push(search ?? "");
    return {
      datasets: state.datasets.map((item) => ({ can_run: true, ...item })),
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
      isLoading: state.casesLoading,
      refetch: state.refetchCases,
    };
  },
}));
vi.mock("@/hooks/use-agents", () => ({
  useJudges: () => ({ agents: state.judges }),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useScoreRun: () => ({ mutateAsync: state.score, isPending: state.pending }),
}));

const SCORE: CaseScore = {
  ...caseScore(),
  id: "s1",
  dataset_id: "d1",
  case_id: "c1",
  case_revision_id: "r1",
  question: "How long is the refund window?",
  reference_answer: null,
  run_id: "run-1",
  run_model: null,
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
      unverified_quotes: [],
      rule: null,
      unverified: false,
      judge_said: null,
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

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "More actions for this run" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Score against a case" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  state.judges = [];
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
  state.casesLoading = false;
  state.caseCalls = [];
  state.searches = [];
  state.holding = [];
  state.holdingLoading = false;
  state.asked = [];
  state.cases = {
    d1: [{ case_id: "c1", input: "How long is the refund window?" }],
    d2: [{ case_id: "c2", input: "x".repeat(100), reference_answer: "Thirty days." }],
  };
  state.turns = [
    { id: "m1", role: "user", content: "  how long is  the refund WINDOW? " },
    { id: "m2", role: "assistant", content: "Thirty days." },
  ];
});

/** Scoring a run from Activity: pick the case, see what each scorer said. */
describe("Score against a case", () => {
  it("picks the case asking the run's question, and shows each scorer's reason", async () => {
    state.score.mockResolvedValue(SCORE);
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() => expect(screen.getByText("Matches the schema")).toBeInTheDocument());
    expect(state.score).toHaveBeenCalledWith({ datasetId: "d1", caseId: "c1", runId: "run-1" });
    expect(state.transcriptOptions).toEqual({ tail: true });
    // The footer's and the dialog's own close both answer to the name.
    await userEvent.click(screen.getAllByRole("button", { name: "Close" })[0]!);
    expect(screen.queryByText("Matches the schema")).toBeNull();
  });

  it("opens on the dataset holding the run's question, not the one changed last", async () => {
    state.score.mockResolvedValue(SCORE);
    state.datasets = [
      { id: "d2", name: "returns" },
      { id: "d1", name: "refunds" },
    ];
    state.holding = [{ id: "d1", name: "refunds" }];
    render(<RunMoreMenu runId="run-1" />);

    await open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("refunds");
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    await waitFor(() =>
      expect(state.score).toHaveBeenCalledWith({ datasetId: "d1", caseId: "c1", runId: "run-1" }),
    );
    // By the run's id: the question itself never goes into a URL.
    expect(state.asked).toEqual(expect.arrayContaining(["run-1"]));
    expect(state.asked).not.toContain("how long is the refund window?");
    // One dataset holds it: nothing to choose between, so nothing is said.
    expect(screen.queryByText(/come first in the list/)).toBeNull();
  });

  it("picks nothing to score against until it knows which datasets hold the question", async () => {
    state.holdingLoading = true;
    state.datasets = [
      { id: "d2", name: "returns" },
      { id: "d1", name: "refunds" },
    ];
    // The newest dataset asks the question too: picked early, a score would land there.
    state.cases.d2 = [{ case_id: "c2", input: "How long is the refund window?" }];
    const { rerender } = render(<RunMoreMenu runId="run-1" />);

    await open();
    expect(screen.getByRole("combobox", { name: "Case" })).toHaveTextContent(
      "Pick a dataset first",
    );
    expect(screen.getByRole("button", { name: "Score" })).toBeDisabled();

    state.holdingLoading = false;
    state.holding = [{ id: "d1", name: "refunds" }];
    rerender(<RunMoreMenu runId="run-1" />);
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("refunds");
    expect(screen.getByRole("button", { name: "Score" })).toBeEnabled();
  });

  it("offers no dataset the caller may not run, holding the question or not", async () => {
    state.datasets = [
      { id: "d3", name: "read only", can_run: false },
      { id: "d1", name: "refunds" },
      { id: "d2", name: "returns" },
    ];
    state.holding = [
      { id: "d3", name: "read only", can_run: false },
      { id: "d1", name: "refunds" },
    ];
    render(<RunMoreMenu runId="run-1" />);

    await open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("refunds");
    // One holding dataset the caller may run: nothing to choose between, so nothing is said.
    expect(screen.queryByText(/come first in the list/)).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "refunds",
      "returns",
    ]);
  });

  it("says when several datasets hold the run's question, and offers them first", async () => {
    state.holding = [
      { id: "d3", name: "faq" },
      { id: "d1", name: "refunds" },
    ];
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(
      screen.getByText(
        "2 datasets have a case asking this run's question; they come first in the list.",
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "faq",
      "refunds",
      "returns",
    ]);
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
    render(<RunMoreMenu runId="run-1" />);

    await open();
    expect(screen.getByText("Runs Checks and Expected tool calls.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Case" }));
    await userEvent.click(screen.getByRole("option", { name: `${"x".repeat(80)}…` }));

    expect(
      screen.getByText(
        "Runs Checks, Expected tool calls, and Reference answer. The judge's grading is a run of the eval judge, charged to its budget.",
      ),
    ).toBeInTheDocument();
  });

  it("names the judge that will grade and its model, and where each is changed", async () => {
    state.datasets = [
      {
        id: "d1",
        name: "refunds",
        judge_name: "Refunds judge",
        scoring: {
          ...DEFAULT_SCORING,
          judge: { ...DEFAULT_SCORING.judge, enabled: true, agent_id: "j1" },
        },
      },
    ];
    state.judges = [
      { id: "j0", name: "Eval judge", system_key: "eval_judge" },
      { id: "j1", name: "Refunds judge", system_key: null, published_model: { label: "GPT-4.1" } },
    ];
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByText("Graded by Refunds judge on GPT-4.1.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change the dataset's judge" })).toHaveAttribute(
      "href",
      "/datasets/d1?tab=grading",
    );
    expect(screen.getByRole("link", { name: "Change the judge's model" })).toHaveAttribute(
      "href",
      "/agents/j1",
    );
  });

  it("names the default judge, unpublished, or only by name when judges cannot be read", async () => {
    state.datasets = [
      {
        id: "d1",
        name: "refunds",
        judge_name: "Eval judge",
        scoring: { ...DEFAULT_SCORING, reference: { enabled: true, required: true } },
      },
    ];
    state.judges = [{ id: "j0", name: "Eval judge", system_key: "eval_judge" }];
    const { unmount } = render(<RunMoreMenu runId="run-1" />);
    await open();
    expect(
      screen.getByText("Graded by Eval judge, which is not published on a model yet."),
    ).toBeInTheDocument();
    unmount();

    state.judges = [];
    render(<RunMoreMenu runId="run-1" />);
    await open();
    expect(screen.getByText("Graded by Eval judge.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Change the judge's model" })).toBeNull();
  });

  it("names no judge for a dataset that grades without one, or one nobody can name", async () => {
    state.datasets = [
      { id: "d1", name: "refunds", judge_name: "Eval judge", scoring: DEFAULT_SCORING },
      {
        id: "d2",
        name: "returns",
        judge_name: null,
        scoring: { ...DEFAULT_SCORING, judge: { ...DEFAULT_SCORING.judge, enabled: true } },
      },
    ];
    render(<RunMoreMenu runId="run-1" />);

    await open();
    expect(screen.queryByText(/Graded by/)).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));

    expect(screen.queryByText(/Graded by/)).toBeNull();
  });

  it("warns of the judge's cost when only the case's own judge check calls it", async () => {
    state.datasets = [{ id: "d1", name: "refunds", scoring: DEFAULT_SCORING }];
    state.cases = { d1: [{ case_id: "c1", input: "Polite?", checks: [{ type: "judge" }] }] };
    state.turns = [{ id: "m1", role: "user", content: "Polite?" }];
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByText(/charged to its budget/)).toBeInTheDocument();
  });

  it("offers a retry when the datasets could not be read, rather than saying there are none", async () => {
    state.datasets = [];
    state.datasetsError = new Error("502");
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(state.refetchDatasets).toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Create one" })).toBeNull();
  });

  it("searches the datasets once there are more than one listing holds", async () => {
    state.datasetTotal = 250;
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.type(screen.getByPlaceholderText("Find a dataset"), "ref");

    await waitFor(() => expect(state.searches).toContain("ref"));
  });

  it("pages through a dataset with more cases than one listing holds", async () => {
    state.caseTotal = 250;
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    expect(state.caseCalls.at(-1)).toEqual({ datasetId: "d1", skip: 100 });
  });

  it.each([
    [{ datasets: [], isLoading: true }, "Pick a dataset first"],
    [{ casesLoading: true, cases: { d1: [] } }, "Loading cases…"],
    [{ cases: { d1: [] } }, "This dataset has no case yet"],
  ])("says what the case picker waits for: %o", async (overrides, shown) => {
    Object.assign(state, overrides);
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByRole("combobox", { name: "Case" })).toHaveTextContent(shown);
  });

  it("says why the cases could not be read", async () => {
    state.casesError = new Error("Cases unavailable");
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByText("Cases unavailable")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetchCases).toHaveBeenCalled();
  });

  it("takes the case from the dataset chosen, shortening a long question", async () => {
    state.score.mockResolvedValue(SCORE);
    render(<RunMoreMenu runId="run-1" />);

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
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("button", { name: "Score" }));

    expect(await screen.findByText("This run kept no answer to score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Score" })).toBeInTheDocument();
  });

  it("points at Datasets when there is nothing to score against", async () => {
    state.datasets = [];
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/datasets");
    expect(screen.getByRole("button", { name: "Score" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });

  it("shows that it is scoring while the judge runs", async () => {
    state.pending = true;
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByRole("button", { name: "Scoring…" })).toBeDisabled();
  });

  it("offers the run's answer as a case when no case asks its question", async () => {
    state.cases = { d1: [{ case_id: "c9", input: "Something else" }] };
    render(<RunMoreMenu runId="run-1" />);

    await open();

    expect(screen.getByRole("combobox", { name: "Case" })).toHaveTextContent(
      "Pick the case to grade against",
    );
    expect(screen.getByRole("button", { name: "Score" })).toBeDisabled();
    expect(
      screen.getByText("No case of this dataset asks this run's question."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add it as a case" }));
    expect(screen.getByRole("dialog", { name: "Add to dataset" })).toHaveTextContent("m2");
  });

  it("lists the cases closest to the run's question first, and drops the note once one is picked", async () => {
    state.cases = {
      d1: [
        { case_id: "c7", input: "Do you ship to Canada?" },
        { case_id: "c8", input: "Can I return shoes?" },
        { case_id: "c9", input: "How long is the window for a refund?" },
      ],
    };
    render(<RunMoreMenu runId="run-1" />);

    await open();
    await userEvent.click(screen.getByRole("combobox", { name: "Case" }));
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "How long is the window for a refund?",
      "Do you ship to Canada?",
      "Can I return shoes?",
    ]);
    await userEvent.click(screen.getByRole("option", { name: "Can I return shoes?" }));

    expect(screen.queryByText("No case of this dataset asks this run's question.")).toBeNull();
    expect(screen.getByRole("button", { name: "Score" })).toBeEnabled();
  });

  it.each([[[]], [null]])(
    "offers nothing to add while the run's turns are unknown: %o",
    async (turns) => {
      state.turns = turns;
      render(<RunMoreMenu runId="run-1" />);

      await open();

      expect(screen.queryByText("No case of this dataset asks this run's question.")).toBeNull();
      expect(screen.getByRole("button", { name: "Score" })).toBeDisabled();
    },
  );
});
