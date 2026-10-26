import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { arm, evalRun, SUMMARY } from "@/test-utils/eval-runs";
import type { EvalRun } from "@/types/eval-runs";
import { TodayCheck } from "./today-check";

const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  start: vi.fn(),
  run: undefined as EvalRun | undefined,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRuns: () => ({
    estimate: { mutateAsync: state.estimate },
    start: { mutateAsync: state.start, isPending: false },
  }),
  useEvalRun: () => ({ run: state.run, error: state.error }),
}));

const REQUEST = {
  dataset_id: "d1",
  candidate: "version",
  model_profile_ids: [],
  paired_baseline: false,
  from_recordings: false,
  live_reads: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  state.run = undefined;
  state.error = null;
  state.estimate.mockResolvedValue({ cases: 12, total_usd: "0.03", affordable: true });
  state.start.mockResolvedValue({ id: "run-9" });
});

it("tests today's version once, priced first, and shows how it did", async () => {
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(await screen.findByText(/12 questions, about .*0\.03.*\(estimate\)/)).toBeInTheDocument();
  expect(state.estimate).toHaveBeenCalledWith(REQUEST);
  await userEvent.click(screen.getByRole("button", { name: "Test how the agent answers today" }));
  expect(state.start).toHaveBeenCalledWith(REQUEST);
  expect(screen.getByRole("status")).toHaveTextContent(/Testing today's answers/);
  state.run = evalRun({
    status: "completed",
    arms: [arm({ role: "candidate", summary: { ...SUMMARY, passed: 9, cases: 12 } })],
  });
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByText("Today the agent handles 9 of 12 questions well.")).toBeInTheDocument();
});

it("does not call an unfinished or failed test a measurement", async () => {
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Test how the agent answers today" }),
  );
  state.run = evalRun({ status: "failed" });
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/did not finish/);
  state.error = new Error("Forbidden");
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

it("keeps an unaffordable test disabled and shows refusals", async () => {
  state.estimate.mockResolvedValue({ cases: 12, total_usd: "9", affordable: false });
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(
    await screen.findByRole("button", { name: "Test how the agent answers today" }),
  ).toBeDisabled();
  view.unmount();
  state.estimate.mockResolvedValue({ cases: 12, total_usd: "0.03", affordable: true });
  state.start.mockRejectedValue(new Error("Budget refused"));
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  await screen.findByText(/12 questions/);
  await userEvent.click(screen.getByRole("button", { name: "Test how the agent answers today" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Budget refused");
});

it("says why the test could not be priced, and drops a late answer", async () => {
  state.estimate.mockRejectedValue(new Error("Nothing to score"));
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Nothing to score");
  let settle: (value: unknown) => void = () => {};
  state.estimate.mockReturnValue(new Promise((resolve) => (settle = resolve)));
  const late = render(<TodayCheck agentId="a1" datasetId="d2" />);
  late.unmount();
  settle({ cases: 1, total_usd: "0", affordable: true });
  let fail: (reason: unknown) => void = () => {};
  state.estimate.mockReturnValue(new Promise((_, reject) => (fail = reject)));
  const failed = render(<TodayCheck agentId="a1" datasetId="d3" />);
  failed.unmount();
  fail(new Error("late"));
  await Promise.resolve();
  expect(state.estimate).toHaveBeenCalledTimes(3);
});
