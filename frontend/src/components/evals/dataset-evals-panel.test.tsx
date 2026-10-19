import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { arm, evalRun } from "@/test-utils/eval-runs";
import { Perm } from "@/types/permissions";
import { DatasetEvalsPanel, DatasetRunEvalsButton } from "./dataset-evals-panel";

const state = vi.hoisted(() => ({
  runs: {} as Record<string, unknown>,
  allowed: new Set<string>(),
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
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => state.allowed.has(permission) }),
}));
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
  state.allowed = new Set([Perm.datasetsRun]);
  state.runs = { runs: [], total: 0, isLoading: false, error: null, refetch: vi.fn() };
});

describe("DatasetEvalsPanel", () => {
  it("folds the runs by agent, each with its trend and verdicts", () => {
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
    const desk = screen.getByText("Refund desk · 2 runs").closest("details")!;
    expect(desk).toHaveAttribute("open");
    expect(within(desk).getByRole("group", { name: "Pass rate by run" })).toBeInTheDocument();
    expect(within(desk).getByRole("link", { name: /^Draft/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-2",
    );
    expect(desk.querySelector("summary .rounded-full")).not.toBeNull();
    const other = screen.getByText("An agent you cannot see · 1 run").closest("details")!;
    expect(other).not.toHaveAttribute("open");
    expect(other.querySelector("summary .rounded-full")).toBeNull();
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
  it("is not offered to who may not run a dataset", () => {
    state.allowed = new Set();
    render(<DatasetRunEvalsButton datasetId="ds-1" />);
    expect(screen.queryByRole("button", { name: "Run evals" })).toBeNull();
  });
});
