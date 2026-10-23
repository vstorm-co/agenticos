import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { arm, comparison, evalRun } from "@/test-utils/eval-runs";
import type { EvalOutcome } from "@/types/eval-runs";
import { DraftEvalNote } from "./draft-eval-note";

const draft = vi.hoisted(() => ({
  runs: [] as unknown[],
  isLoading: false,
  error: null as Error | null,
  refetch: (() => undefined) as () => unknown,
}));
const earlier = vi.hoisted(() => ({
  runs: [] as unknown[],
  isLoading: false,
  error: null as Error | null,
  refetch: (() => undefined) as () => unknown,
  enabled: [] as boolean[],
}));
vi.mock("@/hooks/use-eval-runs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-eval-runs")>()),
  useDraftEvalRuns: (_agentId: string, options?: { draft?: string; enabled?: boolean }) => {
    if (options?.draft !== "earlier") return draft;
    earlier.enabled.push(options.enabled === true);
    return earlier;
  },
}));

const OUTCOME: EvalOutcome = {
  candidate_arm_id: "arm-1",
  verdict: "worse",
  baseline: { ...comparison().candidate, version_number: 1 },
  regressions_confirmed: 4,
  fixed_confirmed: 0,
  candidate_pass_rate: 0.22,
  baseline_pass_rate: 0.67,
  overall: null,
  candidate_first_pass_rate: null,
  baseline_first_pass_rate: null,
};

beforeEach(() => {
  draft.runs = [];
  draft.isLoading = false;
  draft.error = null;
  earlier.runs = [];
  earlier.isLoading = false;
  earlier.error = null;
  earlier.enabled = [];
});

describe("DraftEvalNote", () => {
  it("says the last test could not be read rather than that there was none", async () => {
    draft.error = new Error("boom");
    draft.refetch = vi.fn();
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not read how this draft last tested.",
    );
    expect(screen.queryByText(/was not tested/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(draft.refetch).toHaveBeenCalled();
  });

  it("says a draft made things worse, and links the run that said so", () => {
    draft.runs = [evalRun({ outcome: OUTCOME })];
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    const note = screen.getByRole("link", {
      name: "Last test of this draft: it breaks 4 against v1.",
    });
    expect(note).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(note.className).toContain("text-destructive");
  });

  it("says a draft made things better", () => {
    draft.runs = [evalRun({ outcome: { ...OUTCOME, verdict: "better", fixed_confirmed: 2 } })];
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(screen.getByRole("link", { name: /it fixes 2 against v1/ }).className).toContain(
      "text-success",
    );
  });

  it("says what the draft left ungraded, in a warning however it came out", () => {
    draft.runs = [
      evalRun({
        outcome: { ...OUTCOME, verdict: "better", fixed_confirmed: 1 },
        arms: [arm({ ungraded_cases: [{ case_id: "c1", input: "$700 TV, can I return it?" }] })],
      }),
    ];
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    const note = screen.getByRole("link", { name: /it fixes 1 against v1/ });
    expect(note).toHaveTextContent(
      "1 case of this draft was not graded: “$700 TV, can I return it?”. Grade again on the run before publishing.",
    );
    expect(note.className).toContain("text-warning");
  });

  it("says a draft was mixed", () => {
    draft.runs = [evalRun({ outcome: { ...OUTCOME, verdict: "mixed", fixed_confirmed: 2 } })];
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(
      screen.getByRole("link", { name: /mixed against v1, 4 broke and 2 fixed/ }).className,
    ).toContain("text-warning");
  });

  it("says a first result has nothing to compare with, and a live run is still testing", () => {
    draft.runs = [evalRun({ outcome: { ...OUTCOME, verdict: null, baseline: null } })];
    const { rerender } = render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(screen.getByRole("link", { name: /the first result/ }).className).toContain(
      "text-muted-foreground",
    );

    draft.runs = [evalRun({ status: "running", outcome: null })];
    rerender(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(screen.getByRole("link", { name: "This draft is being tested now." })).toBeVisible();

    // A run that ended with no verdict is not still testing.
    for (const [status, said] of [
      ["cancelled", "was stopped"],
      ["budget_exceeded", "ran out of budget"],
      ["failed", "failed"],
    ] as const) {
      draft.runs = [evalRun({ status, outcome: null })];
      rerender(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
      expect(
        screen.getByRole("link", {
          name: `The last test of this draft ${said} before it reached a verdict.`,
        }),
      ).toBeVisible();
    }
  });

  it("offers to test a draft nobody tested since it changed", async () => {
    const onTest = vi.fn();
    render(<DraftEvalNote agentId="agent-1" onTest={onTest} />);
    expect(screen.getByText("This draft was not tested since it last changed.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Test it" }));
    expect(onTest).toHaveBeenCalled();
  });

  it("says a test of an earlier draft is out of date, and offers a new one", async () => {
    earlier.runs = [evalRun({ outcome: OUTCOME })];
    const onTest = vi.fn();
    render(<DraftEvalNote agentId="agent-1" onTest={onTest} />);
    expect(
      screen.getByText("This draft changed since its last test, so that result is out of date."),
    ).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Test it" }));
    expect(onTest).toHaveBeenCalled();
  });

  it("says it could not tell when the lookup of an earlier test failed, and retries it", async () => {
    earlier.error = new Error("boom");
    earlier.refetch = vi.fn();
    const onTest = vi.fn();
    render(<DraftEvalNote agentId="agent-1" onTest={onTest} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not read how this draft last tested.",
    );
    expect(screen.queryByText(/was not tested/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(earlier.refetch).toHaveBeenCalled();
    expect(onTest).not.toHaveBeenCalled();
  });

  it("asks about an earlier draft only when this one has no test", () => {
    draft.runs = [evalRun({ outcome: OUTCOME })];
    render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(earlier.enabled).toEqual([false]);
  });

  it("says nothing while it reads", () => {
    draft.isLoading = true;
    const { container, rerender } = render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();

    draft.isLoading = false;
    earlier.isLoading = true;
    rerender(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
