import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { evalRun } from "@/test-utils/eval-runs";
import { SESSION } from "@/test-utils/improvement";
import type { EvalRun } from "@/types/eval-runs";
import type { Improvement } from "@/types/improvement";
import { CheckProgress } from "./check-progress";

const state = vi.hoisted(() => ({
  run: undefined as EvalRun | undefined,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: () => ({ run: state.run, error: state.error, refetch: state.refetch }),
}));

const RUNNING: Improvement = {
  ...SESSION,
  status: "running",
  stage: "evaluating",
  iterations: [{ ...SESSION.iterations[0]!, verdict: null }],
};

beforeEach(() => {
  state.run = undefined;
  state.error = null;
});

function stageOf(text: RegExp) {
  return screen.getByText(text).closest("li")!.textContent;
}

it("walks through asking, grading and re-asking while the test runs", () => {
  state.run = evalRun({
    status: "running",
    cases: 12,
    first_done: 3,
    first_total: 24,
    attempts_done: 3,
    attempts_total: 24,
  });
  const view = render(<CheckProgress session={RUNNING} onShowResult={vi.fn()} />);
  expect(screen.getByText("On 12 questions.")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Testing the changes" })).toBeInTheDocument();
  expect(stageOf(/Asking the improved agent/).startsWith("Asking")).toBe(true);
  expect(stageOf(/Asking the improved agent/)).toMatch(/Running$/);
  expect(stageOf(/^Grading/)).toMatch(/Not started$/);
  expect(stageOf(/Re-asking answers whose result changed/)).toMatch(/Not started$/);
  expect(screen.getByRole("status")).toHaveTextContent(/close this page/);
  state.run = { ...state.run, first_done: 24, attempts_total: 26, attempts_done: 24 };
  view.rerender(
    <CheckProgress session={{ ...RUNNING, stage: "judging" }} onShowResult={vi.fn()} />,
  );
  expect(stageOf(/Asking the improved agent/)).toMatch(/Done$/);
  expect(screen.getByText(/^Grading/).closest("li")).toHaveAttribute("aria-current", "step");
  expect(stageOf(/^Grading/)).toMatch(/Running$/);
  expect(stageOf(/Re-asking 2 answers whose result changed/)).toMatch(/Running$/);
  state.run = { ...state.run, status: "completed" };
  view.rerender(<CheckProgress session={RUNNING} onShowResult={vi.fn()} />);
  expect(stageOf(/Re-asking 2 answers/)).toMatch(/Done$/);
});

it("says the test is being prepared before it has a run, and retries a failed read", async () => {
  const view = render(
    <CheckProgress
      session={{ ...RUNNING, iterations: [{ ...RUNNING.iterations[0]!, eval_run_ids: [] }] }}
      onShowResult={vi.fn()}
    />,
  );
  expect(screen.getByText("Preparing the test…")).toBeInTheDocument();
  view.rerender(<CheckProgress session={RUNNING} onShowResult={vi.fn()} />);
  expect(screen.getByText("Loading the result…")).toBeInTheDocument();
  state.error = new Error("Forbidden");
  view.rerender(<CheckProgress session={RUNNING} onShowResult={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
  expect(state.refetch).toHaveBeenCalled();
});

it("leads to the result once the test has finished", async () => {
  const show = vi.fn();
  render(<CheckProgress session={SESSION} onShowResult={show} />);
  expect(screen.getByText("The test has finished.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "See the result" }));
  expect(show).toHaveBeenCalled();
});

it("explains a test the budget did not allow, and one that never ran", () => {
  const unmeasured = { ...SESSION, status: "stopped" as const, iterations: RUNNING.iterations };
  const view = render(
    <CheckProgress session={{ ...unmeasured, stop_reason: "budget" }} onShowResult={vi.fn()} />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(/Raise the limit to continue/);
  expect(screen.queryByText(/No test ran/)).not.toBeInTheDocument();
  view.rerender(<CheckProgress session={unmeasured} onShowResult={vi.fn()} />);
  expect(screen.getByText("No test ran in this session.")).toBeInTheDocument();
});
