import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { comparison, evalRun } from "@/test-utils/eval-runs";
import type { EvalOutcome } from "@/types/eval-runs";
import { DraftEvalNote } from "./draft-eval-note";

const draft = vi.hoisted(() => ({ runs: [] as unknown[], isLoading: false }));
vi.mock("@/hooks/use-eval-runs", () => ({ useDraftEvalRuns: () => draft }));

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
});

describe("DraftEvalNote", () => {
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
  });

  it("offers to test a draft nobody tested since it changed", async () => {
    const onTest = vi.fn();
    render(<DraftEvalNote agentId="agent-1" onTest={onTest} />);
    expect(screen.getByText("This draft was not tested since it last changed.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Test it" }));
    expect(onTest).toHaveBeenCalled();
  });

  it("says nothing while it reads", () => {
    draft.isLoading = true;
    const { container } = render(<DraftEvalNote agentId="agent-1" onTest={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
