import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { arm, evalRun } from "@/test-utils/eval-runs";
import { DatasetEvalsPanel, DatasetRunEvalsButton } from "./dataset-evals-panel";

const state = vi.hoisted(() => ({
  runs: {} as Record<string, unknown>,
  dataset: undefined as { can_run: boolean; run_needs: string[] } | undefined,
  dialog: [] as unknown[],
  skips: [] as number[],
}));
vi.mock("@/hooks/use-eval-runs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-eval-runs")>()),
  useDatasetEvalRuns: (_id: string, { skip }: { skip: number }) => {
    state.skips.push(skip);
    return state.runs;
  },
  useEveryAgent: () => ({
    agents: [{ id: "agent-1", name: "Refund desk", slug: "refund-desk", has_avatar: true }],
  }),
}));
vi.mock("@/hooks/use-datasets", () => ({ useDataset: () => ({ dataset: state.dataset }) }));
vi.mock("./start-eval-dialog", () => ({
  StartEvalDialog: (props: {
    datasetId: string;
    agentId: string | null;
    onOpenChange: (open: boolean) => void;
  }) => {
    state.dialog.push(props);
    return <button onClick={() => props.onOpenChange(false)}>start-dialog</button>;
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.dialog = [];
  state.skips = [];
  state.dataset = { can_run: true, run_needs: [] };
  state.runs = { runs: [], total: 0, isLoading: false, error: null, refetch: vi.fn() };
});

describe("DatasetEvalsPanel", () => {
  it.each(["failed", "cancelled"] as const)(
    "keeps %s status in the mobile run summary",
    (status) => {
      state.runs = { ...state.runs, runs: [evalRun({ status, outcome: null })], total: 1 };
      render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);
      const link = screen.getByRole("link", { name: /Refund desk/ });
      expect(
        within(link).getByText(status === "failed" ? "Failed" : "Stopped"),
      ).toBeInTheDocument();
    },
  );
  it("shows every run in one table with its agent, pass rate and result", () => {
    state.runs = {
      ...state.runs,
      runs: [
        evalRun({ id: "run-2", arms: [arm({ source: "draft", version_number: null })] }),
        evalRun(),
        evalRun({ id: "run-3", agent_id: "hidden" }),
      ],
      total: 3,
    };
    render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);

    expect(screen.getByText("3 runs of 2 agents")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Pass rate" })).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("link")
        .some((link) => link.getAttribute("href") === "/agents/agent-1/evals/run-2"),
    ).toBe(true);
    expect(screen.getAllByText(/An agent you cannot see/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Pass-rate trend" })).toBeNull();
    const trend = screen.getByRole("region", { name: "Pass-rate trend" });
    expect(trend).toBeVisible();
    expect(
      trend.compareDocumentPosition(screen.getByRole("table")) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("pages through a history longer than one page, counting every run", async () => {
    state.runs = { ...state.runs, runs: [evalRun()], total: 150 };
    render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);
    expect(screen.getAllByText("150 runs")[0]).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(state.skips.at(-1)).toBe(100);
  });

  it("offers the first run when no agent was tested on it", async () => {
    render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByText("No agent has been tested on this dataset yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Run evals" }));
    expect(state.dialog.at(-1)).toEqual(
      expect.objectContaining({ agentId: null, datasetId: "ds-1" }),
    );
    await userEvent.click(screen.getByText("start-dialog"));
    expect(screen.queryByText("start-dialog")).toBeNull();
  });

  it("says when the runs could not be read, and retries", async () => {
    const refetch = vi.fn();
    state.runs = { runs: [], isLoading: false, error: new Error("boom"), refetch };
    const { container } = render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);
    // The header's count line resolves to nothing rather than waiting forever.
    expect(container.querySelector(".animate-pulse")).toBeNull();
    expect(screen.queryByText("No runs yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a placeholder while the runs load", () => {
    state.runs = { ...state.runs, isLoading: true };
    render(<DatasetEvalsPanel datasetId="ds-1" title="Evals" />);
    expect(screen.getByText("Evals")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("DatasetRunEvalsButton", () => {
  it.each([[["datasets:run"]], [["runs:view", "datasets:run"]]])(
    "is not offered to who may not run this dataset at all: %j",
    (needs) => {
      state.dataset = { can_run: false, run_needs: needs };
      render(<DatasetRunEvalsButton datasetId="ds-1" />);
      expect(screen.queryByRole("button", { name: /Run evals/ })).toBeNull();
    },
  );

  it("waits for the dataset rather than offering a run it cannot vouch for", () => {
    state.dataset = undefined;
    render(<DatasetRunEvalsButton datasetId="ds-1" />);
    expect(screen.queryByRole("button", { name: "Run evals" })).toBeNull();
  });

  it("is shown disabled, saying why, to who may run the dataset but not read runs", async () => {
    state.dataset = { can_run: false, run_needs: ["runs:view"] };
    render(<DatasetRunEvalsButton datasetId="ds-1" />);

    const button = screen.getByRole("button", { name: /Run evals/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("title", "Needs permission to read runs");
    await userEvent.click(button);
    expect(state.dialog).toEqual([]);
  });
});

it("offers review only when a completed evaluation exists", async () => {
  const onReview = vi.fn();
  state.runs = { ...state.runs, runs: [evalRun({ status: "running" })], total: 1 };
  const { rerender } = render(
    <DatasetEvalsPanel datasetId="ds-1" title="Evals" onReview={onReview} />,
  );
  expect(screen.queryByRole("button", { name: "Review results" })).toBeNull();
  state.runs = { ...state.runs, runs: [evalRun({ status: "completed" })] };
  rerender(<DatasetEvalsPanel datasetId="ds-1" title="Evals" onReview={onReview} />);
  await userEvent.click(screen.getByRole("button", { name: "Review results" }));
  expect(onReview).toHaveBeenCalledOnce();
});
