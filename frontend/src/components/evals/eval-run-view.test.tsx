import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FLIP, SUMMARY, arm, attempt, comparison, evalCase, evalRun } from "@/test-utils/eval-runs";
import { Perm } from "@/types/permissions";
import { EvalRunView } from "./eval-run-view";

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}));

const review = vi.hoisted(() => ({ canEdit: false, mutate: vi.fn() }));
vi.mock("@/hooks/use-datasets", () => ({
  useDataset: () => ({ dataset: { can_edit: review.canEdit } }),
}));

const access = vi.hoisted(() => ({ allowed: new Set<string>() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => access.allowed.has(permission) }),
}));

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
    useSendToReview: () => ({ mutate: review.mutate, isPending: false }),
    useEvalComparison: (...args: unknown[]) => {
      state.comparisonArgs.push(args);
      return { comparison: state.comparison, refetch: state.refetchComparison };
    },
  };
});

const cancel = { mutate: vi.fn() };
const testAgain = vi.hoisted(() => ({ props: [] as unknown[] }));
vi.mock("./start-eval-dialog", () => ({
  StartEvalDialog: (props: { onOpenChange: (open: boolean) => void }) => {
    testAgain.props.push(props);
    return <button onClick={() => props.onOpenChange(false)}>start-dialog</button>;
  },
}));

/** A draft measured against v6 in the same run, which it made worse. */
function worseDraft() {
  state.run = {
    ...state.run,
    run: evalRun({
      arms: [
        arm({ source: "draft", version_number: null, agent_version_id: null }),
        arm({ id: "arm-0", role: "baseline", version_number: 6 }),
      ],
      attempts_total: 6,
    }),
  };
  state.comparison = comparison({
    candidate: { ...comparison().candidate, source: "draft", version_number: null },
    baseline: { ...comparison().candidate, run_id: "run-1", arm_id: "arm-0", version_number: 6 },
    paired: true,
    verdict: "worse",
    regressions_confirmed: 4,
    fixed_unconfirmed: 0,
    candidate_summary: { ...SUMMARY, pass_rate: 0.22 },
    baseline_summary: { ...SUMMARY, pass_rate: 0.67 },
    cases: [FLIP, { ...FLIP, case_id: "case-2", flip: "unchanged" }],
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  review.canEdit = false;
  review.mutate = vi.fn();
  access.allowed = new Set();
  state.casesArgs = [];
  state.comparisonArgs = [];
  state.run = { run: evalRun(), isLoading: false, error: null, refetch: vi.fn(), cancel };
  state.cases = { cases: [evalCase()], total: 1, isLoading: false, error: null };
  state.comparison = comparison();
});

describe("EvalRunView", () => {
  it("leads with the verdict, then each side, how they compare and every case", async () => {
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText("refunds v3 · v7")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /Not sure yet.*2 cases changed between Draft and v7/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("4 cases · 4 answers + no confirming reruns")).toBeInTheDocument();
    expect(
      screen.getByText(
        /spent \$0.04 of an estimated \$0.05, plus up to \$0.02 for confirming reruns/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the agent's evals" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=evals",
    );
    expect(screen.getByRole("link", { name: "Back to Build" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build",
    );
    // A published version is not what Publish acts on, and the draft was not measured.
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
    expect(screen.queryByRole("link", { name: "See what changed" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.getByText("How the two compare")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Undecided" })).toBeInTheDocument();

    const caseRow = screen.getByRole("button", { name: /How long do I have to return it/ });
    expect(within(caseRow).getByRole("img", { name: "v7 · gpt-4.1: passed" })).toBeVisible();
    expect(within(caseRow).getByText("Confirmed regression")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.getByText("You have 30 days.")).toBeInTheDocument();
    await userEvent.click(caseRow);
    expect(screen.queryByText("You have 30 days.")).not.toBeInTheDocument();
  });

  it("says a draft made things worse, what changed, and shows the cases that broke", async () => {
    worseDraft();
    access.allowed = new Set([Perm.agentsPublish]);
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(
      screen.getByRole("heading", {
        name: /Draft is worse than v6 on refunds: 4 cases broke \(confirmed\), 0 fixed\. Pass rate 67% → 22%\./,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 answers \+ 2 confirming reruns/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See what changed" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=history&from=6&run=run-1&arm=arm-1",
    );
    expect(screen.getByRole("link", { name: "Publish" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build&publish=1",
    );

    await userEvent.click(screen.getByRole("button", { name: "Show the 4 cases that broke" }));
    expect(state.casesArgs.at(-1)).toEqual([
      "run-1",
      expect.objectContaining({ caseIds: ["case-1"], skip: 0 }),
    ]);
    expect(screen.getByText("Showing the case that broke.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show every case" }));
    expect(state.casesArgs.at(-1)).toEqual(["run-1", expect.objectContaining({ caseIds: null })]);
  });

  it("puts Publish first only when nothing broke for sure", () => {
    worseDraft();
    state.comparison = {
      ...(state.comparison as object),
      verdict: "better",
      regressions_confirmed: 0,
    };
    access.allowed = new Set([Perm.agentsPublish]);
    const { unmount } = render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("heading", { name: /Draft is better than v6/ })).toBeVisible();
    expect(screen.getByRole("link", { name: "Publish" }).className).toContain("bg-primary");
    unmount();

    // A confirmed regression is a reason not to publish, even when the sample
    // is too small for a verdict.
    state.comparison = {
      ...(state.comparison as object),
      verdict: "inconclusive",
      regressions_confirmed: 3,
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("link", { name: "Publish" }).className).not.toContain("bg-primary");
  });

  it("shows no verdict for a run with no candidate to give one about", () => {
    state.run = { ...state.run, run: evalRun({ arms: [] }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("link", { name: "Back to Build" })).toBeNull();
  });

  it("names no rerun allowance when a run had none", () => {
    state.run = { ...state.run, run: evalRun({ rerun_ceiling_usd: "0" }) };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText(/of an estimated \$0.05$/)).toBeInTheDocument();
  });

  it("sends what failed to review, for who may edit the dataset", async () => {
    review.canEdit = true;
    review.mutate = vi.fn((_arm: unknown, options: { onSuccess: (sent: unknown) => void }) =>
      options.onSuccess({ queued: 1, already: 0 }),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    await userEvent.click(screen.getByRole("button", { name: "Send the failed case to review" }));

    expect(review.mutate).toHaveBeenCalledWith("arm-1", expect.anything());
    expect(toastSuccess).toHaveBeenCalledWith("1 case sent to review.");
  });

  it("says when sending to review was refused", async () => {
    review.canEdit = true;
    review.mutate = vi.fn((_arm: unknown, options: { onError: (e: Error) => void }) =>
      options.onError(new Error("refused")),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    await userEvent.click(screen.getByRole("button", { name: /to review/ }));
    expect(toastError).toHaveBeenCalled();
  });

  it("offers no review to who may not edit the dataset, or when nothing failed", () => {
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: /to review/ })).toBeNull();
    cleanup();

    review.canEdit = true;
    state.run = {
      ...state.run,
      run: evalRun({ arms: [arm({ summary: { ...SUMMARY, failed: 0 } })] }),
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("button", { name: /to review/ })).toBeNull();
  });

  it("marks a case a person's review overturned", () => {
    state.cases = {
      cases: [
        evalCase({
          attempts: [
            attempt({
              outcome: true,
              score: { id: "s1", passed: false, human_passed: true } as never,
            }),
          ],
        }),
      ],
      total: 1,
      isLoading: false,
      error: null,
    };
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("Corrected by a person")).toBeInTheDocument();
  });

  it("offers to test again, not to publish, once the draft moved on", async () => {
    worseDraft();
    state.run = { ...state.run, run: { ...(state.run.run as object), draft_changed: true } };
    access.allowed = new Set([Perm.agentsPublish]);
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
    expect(screen.getByText("The draft changed after this run.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Test again" }));
    expect(testAgain.props.at(-1)).toEqual(
      expect.objectContaining({ agentId: "agent-1", datasetId: "ds-1", target: "compare" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "start-dialog" }));
    expect(screen.queryByRole("button", { name: "start-dialog" })).toBeNull();
  });

  it("offers no publish to who may not publish", () => {
    worseDraft();
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.queryByRole("link", { name: "Publish" })).toBeNull();
  });

  it("calls a run with nothing before it the first result", () => {
    state.comparison = comparison({
      baseline: null,
      verdict: null,
      regressions_confirmed: 0,
      fixed_unconfirmed: 0,
      baseline_summary: null,
      cases: [],
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(
      screen.getByRole("heading", {
        name: "This is the first result of v7 on refunds: 75% of cases pass. Later versions are compared with it.",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("How the two compare")).toBeNull();
    expect(screen.queryByRole("button", { name: /that broke/ })).toBeNull();
  });

  it("says why two sides cannot be compared", () => {
    state.comparison = comparison({
      verdict: "invalid",
      invalid_reason: "The two sides were graded by a different judge, model or rubric.",
      baseline_summary: null,
    });
    render(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByRole("heading", { name: /v7 and Draft cannot be compared/ })).toBeVisible();
    expect(screen.getByText(/graded by a different judge, model or rubric/)).toBeVisible();
  });

  it("while it answers, says how far it got and holds the comparison back", async () => {
    state.run = {
      ...state.run,
      run: evalRun({
        status: "running",
        first_done: 1,
        attempts_done: 1,
        error: "A case ran into a budget.",
      }),
    };
    state.cases = {
      cases: [evalCase({ attempts: [attempt({ status: "running", outcome: null })] })],
      total: 1,
      isLoading: false,
      error: null,
    };
    cancel.mutate.mockImplementation((_: unknown, options: { onError: (e: Error) => void }) =>
      options.onError(new Error("Only whoever started this eval can stop it")),
    );
    render(<EvalRunView agentId="agent-1" runId="run-1" />);

    expect(screen.getByText(/1 of 4 first answers in/)).toBeInTheDocument();
    expect(screen.getByText("The comparison appears when both sides finish.")).toBeVisible();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByText("How the two compare")).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Pending" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: pending" })).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("option", { name: "v7 · claude" }));
    expect(state.comparisonArgs.at(-1)).toEqual(["run-1", { arm: "arm-2", live: false }]);
  });

  it("filters the cases by outcome and tag, back to the first page", async () => {
    state.cases = {
      cases: [
        evalCase({ attempts: [attempt({ outcome: false })] }),
        evalCase({
          case_id: "case-2",
          input: "Lost receipt?",
          tags: [],
          attempts: [attempt({ outcome: null })],
        }),
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
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: failed" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "v7 · gpt-4.1: undecided" })).toBeInTheDocument();

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
          arm({ id: "arm-0", role: "baseline", version_number: 6, by_tag: {} }),
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

    expect(screen.getByText("Side by side on #refunds")).toBeInTheDocument();
    const candidate = screen.getByRole("row", { name: /v7 · gpt-4\.1/ });
    const baseline = screen.getByRole("row", { name: /v6 · gpt-4\.1/ });
    expect(within(candidate).getByText("50%")).toBeInTheDocument();
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
    expect(screen.getByText("Side by side")).toBeInTheDocument();
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
    expect(screen.queryByRole("combobox", { name: "Tag" })).not.toBeInTheDocument();
    expect(screen.queryByText("How the two compare")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();

    state.cases = { cases: [], total: 0, isLoading: false, error: new Error("boom") };
    rerender(<EvalRunView agentId="agent-1" runId="run-1" />);
    expect(screen.getByText("refunds v3 · v7")).toBeInTheDocument();
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
