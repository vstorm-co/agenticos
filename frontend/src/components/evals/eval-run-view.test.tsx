import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FLIP, SUMMARY, arm, attempt, comparison, evalCase, evalRun } from "@/test-utils/eval-runs";
import { EvalRunView } from "./eval-run-view";

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

const state = vi.hoisted(() => ({
  run: {} as Record<string, unknown>,
  cases: {} as Record<string, unknown>,
  comparison: undefined as unknown,
  casesArgs: [] as unknown[],
  comparisonArgs: [] as unknown[],
  refetchComparison: (() => undefined) as () => unknown,
}));
vi.mock("@/hooks/use-eval-runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-eval-runs")>();
  return {
    ...actual,
    useEvalRun: () => state.run,
    useEvalCases: (...args: unknown[]) => {
      state.casesArgs.push(args);
      return state.cases;
    },
    useEvalComparison: (...args: unknown[]) => {
      state.comparisonArgs.push(args);
      return { comparison: state.comparison, refetch: state.refetchComparison };
    },
  };
});

const cancel = { mutate: vi.fn() };

beforeEach(() => {
  vi.clearAllMocks();
  state.casesArgs = [];
  state.comparisonArgs = [];
  state.run = { run: evalRun(), isLoading: false, error: null, refetch: vi.fn(), cancel };
  state.cases = { cases: [evalCase()], total: 1, isLoading: false, error: null };
  state.comparison = comparison();
});

describe("EvalRunView", () => {
  it("shows where the run is, how each arm did, how it compares and every case", async () => {
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByRole("heading", { name: "refunds v3 · v7" })).toBeInTheDocument();
    expect(screen.getByText(/spent \$0.04 of an estimated \$0.05/)).toBeInTheDocument();
    expect(screen.getByText("4 of 4 answers")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the agent's evals" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=evals",
    );
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.getByText("Sample too small")).toBeInTheDocument();

    const caseRow = screen.getByRole("button", { name: /How long do I have to return it/ });
    expect(within(caseRow).getByText("Confirmed regression")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.getByText("You have 30 days.")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.queryByText("You have 30 days.")).not.toBeInTheDocument();
  });

  it("stops a live run and says when stopping was refused", async () => {
    state.run = {
      ...state.run,
      run: evalRun({ status: "running", attempts_done: 1, error: "A case ran into a budget." }),
    };
    cancel.mutate.mockImplementation((_: unknown, options: { onError: (e: Error) => void }) =>
      options.onError(new Error("Only whoever started this eval can stop it")),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText("A case ran into a budget.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(cancel.mutate).toHaveBeenCalled();
    expect(toastError).toHaveBeenCalled();
    // A live run's table and its verdict are read again while it answers.
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ live: true })]);
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-1", live: true }]);
  });

  it("reads the verdict once more when the run ends, after its last reruns", () => {
    const refetch = vi.fn();
    state.refetchComparison = refetch;
    state.run = { ...state.run, run: evalRun({ status: "running" }) };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(refetch).not.toHaveBeenCalled();

    state.run = { ...state.run, run: evalRun({ status: "completed" }) };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("compares the model a reader picks when several ran", async () => {
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm(), arm({ id: "arm-2", model_label: "claude" })] }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-1", live: false }]);

    await userEvent.click(screen.getByRole("combobox", { name: "Compare this model" }));
    await userEvent.click(screen.getByRole("option", { name: "claude" }));
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-2", live: false }]);
  });

  it("filters the cases by outcome and tag, back to the first page", async () => {
    state.cases = {
      cases: [
        evalCase({ attempts: [attempt()] }),
        evalCase({ case_id: "case-2", input: "Lost receipt?", tags: [] }),
      ],
      total: 60,
      isLoading: false,
      error: null,
    };
    state.comparison = comparison({
      cases: [
        { ...FLIP, flip: "fixed", confirmed: false },
        { ...FLIP, case_id: "case-2", flip: "unchanged" },
      ],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Fixed, unconfirmed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ skip: 25 })]);

    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "Failed" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: "failed", tag: null, skip: 0 }),
    ]);
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "#refunds" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: "failed", tag: "refunds" }),
    ]);
    await userEvent.click(screen.getByRole("combobox", { name: "Outcome" }));
    await userEvent.click(screen.getByRole("option", { name: "All outcomes" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "All tags" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ outcome: null, tag: null }),
    ]);
  });

  it("reads the arms, the flips and the cases under the tag a reader picks", async () => {
    state.run = {
      ...state.run,
      run: evalRun({
        arms: [
          arm({ by_tag: { refunds: { ...SUMMARY, pass_rate: 0.5 } } }),
          arm({ id: "arm-0", role: "baseline", by_tag: {} }),
        ],
      }),
    };
    state.comparison = comparison({
      regressions_confirmed: 1,
      fixed_confirmed: 1,
      fixed_unconfirmed: 0,
      cases: [FLIP, { ...FLIP, case_id: "case-2", flip: "fixed", tags: ["shipping"] }],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    const count = (label: string) => screen.getByText(label).nextSibling?.textContent;
    expect(count("Confirmed fixes")).toBe("1");

    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "#refunds" }));

    expect(screen.getByText("Results for #refunds")).toBeInTheDocument();
    const candidate = screen.getByRole("row", { name: /Candidate on/ });
    const baseline = screen.getByRole("row", { name: /Baseline on/ });
    expect(within(candidate).getByText("50%")).toBeInTheDocument();
    // The baseline answered no case under the tag, so it has nothing to show.
    expect(within(baseline).getAllByText("—").length).toBeGreaterThan(0);
    expect(count("Confirmed regressions")).toBe("1");
    expect(count("Confirmed fixes")).toBe("0");
    expect(screen.getByText(/1 case tagged #refunds compared/)).toBeInTheDocument();
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ tag: "refunds", skip: 0 }),
    ]);

    await userEvent.click(screen.getByRole("combobox", { name: "Tag" }));
    await userEvent.click(screen.getByRole("option", { name: "All tags" }));
    expect(screen.getByText("Results")).toBeInTheDocument();
    expect(count("Confirmed fixes")).toBe("1");
  });

  it("holds placeholders while the cases load, and says when they could not be read", () => {
    state.comparison = undefined;
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm({ by_tag: {} })], attempts_done: 0, attempts_total: 0 }),
    };
    state.cases = { cases: [], total: 0, isLoading: true, error: null };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("0 of 0 answers")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Tag" })).not.toBeInTheDocument();
    expect(screen.queryByText("Against the baseline")).not.toBeInTheDocument();

    state.cases = { cases: [], total: 0, isLoading: false, error: new Error("boom") };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("heading", { name: "refunds v3 · v7" })).toBeInTheDocument();
  });

  it("holds a placeholder while the run loads, and offers a retry when it cannot be read", async () => {
    state.run = { ...state.run, run: undefined, isLoading: true };
    const { rerender } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    const refetch = vi.fn();
    state.run = { run: undefined, isLoading: false, error: new Error("gone"), refetch, cancel };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });
});
