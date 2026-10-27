import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useOrgStore } from "@/stores";
import { arm, evalRun, SUMMARY } from "@/test-utils/eval-runs";
import type { EvalRun } from "@/types/eval-runs";
import { TodayCheck } from "./today-check";

const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  start: vi.fn(),
  run: undefined as EvalRun | undefined,
  error: null as Error | null,
  kept: [] as EvalRun[],
  keptLoading: false,
  draftQuery: undefined as unknown,
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRuns: () => ({
    estimate: { mutateAsync: state.estimate },
    start: { mutateAsync: state.start, isPending: false },
  }),
  useDraftEvalRuns: (_agentId: string, options: unknown) => {
    state.draftQuery = options;
    return { runs: state.kept, isLoading: state.keptLoading };
  },
  useEvalRun: (runId: string) => ({
    run: state.run && { ...state.run, id: runId },
    error: state.error,
  }),
}));
vi.mock("@/lib/assistant-highlight", () => ({ pointAt: vi.fn() }));

const ONCE = {
  dataset_id: "d1",
  candidate: "draft",
  model_profile_ids: [],
  paired_baseline: false,
  from_recordings: false,
  live_reads: false,
};
const TWICE = { ...ONCE, stability: true };
const BUTTON = "Test how the agent answers today";

function estimate(cases: number, total = "0.03", ceiling = "0.02", affordable = true) {
  return { cases, total_usd: total, rerun_ceiling_usd: ceiling, affordable };
}

function finished(overrides: Partial<EvalRun> = {}): EvalRun {
  return evalRun({
    dataset_id: "d1",
    status: "completed",
    arms: [arm({ role: "candidate", summary: { ...SUMMARY, passed: 9, cases: 12 } })],
    ...overrides,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.run = undefined;
  state.error = null;
  state.kept = [];
  state.keptLoading = false;
  useOrgStore.setState({ activeOrgId: "o1" });
  state.estimate.mockResolvedValue(estimate(12));
  state.start.mockResolvedValue({ id: "run-9" });
});

it("asks the draft each question twice under 40 questions, priced in full", async () => {
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(await screen.findByText(/12 questions, about .*0\.05.*\(estimate\)/)).toBeInTheDocument();
  expect(state.draftQuery).toEqual({ limit: 20 });
  expect(state.estimate).toHaveBeenCalledWith(TWICE);
  expect(screen.getByRole("checkbox", { name: /Ask each question twice/ })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: BUTTON }));
  expect(state.start).toHaveBeenCalledWith(TWICE);
  expect(screen.getByRole("status")).toHaveTextContent(/Testing today's answers/);
  state.run = finished({ stability: { asked: 12, unstable: 1, noisy: false } });
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByText("Today the agent handles 9 of 12 questions well.")).toBeInTheDocument();
  expect(
    screen.getByText("1 of 12 questions was graded differently when asked again."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("asks once at 40 questions and more, and twice when switched back on", async () => {
  state.estimate.mockResolvedValue(estimate(40));
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  const twice = screen.getByRole("checkbox", { name: /Ask each question twice/ });
  expect(await screen.findByText(/40 questions, about .*0\.03.*\(estimate\)/)).toBeInTheDocument();
  expect(twice).not.toBeChecked();
  expect(state.estimate).toHaveBeenLastCalledWith(ONCE);
  await userEvent.click(screen.getByRole("button", { name: BUTTON }));
  expect(state.start).toHaveBeenCalledWith(ONCE);
});

it("lets a small test be asked once", async () => {
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  await screen.findByText(/12 questions/);
  await userEvent.click(screen.getByRole("checkbox", { name: /Ask each question twice/ }));
  expect(await screen.findByText(/12 questions, about .*0\.03.*\(estimate\)/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: BUTTON }));
  expect(state.start).toHaveBeenCalledWith(ONCE);
});

it("shows the newest test of the draft on this dataset after a refresh, a stability one first", () => {
  state.kept = [
    evalRun({ id: "other-dataset", dataset_id: "d2", purpose: "stability" }),
    evalRun({ id: "compared", dataset_id: "d1", arms: [arm(), arm({ role: "baseline" })] }),
    evalRun({ id: "plain", dataset_id: "d1", purpose: "manual" }),
    evalRun({ id: "steady", dataset_id: "d1", purpose: "stability" }),
  ];
  state.run = finished({ stability: { asked: 10, unstable: 3, noisy: true } });
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(state.estimate).not.toHaveBeenCalled();
  expect(
    screen.getByText("3 of 10 questions were graded differently when asked again."),
  ).toBeInTheDocument();
  const warning = screen.getByRole("alert");
  expect(warning).toHaveTextContent(
    "This session will most likely show nothing: the answers or the grading are unstable.",
  );
  expect(
    within(warning).getByRole("link", { name: "Make the grading criteria yes/no questions" }),
  ).toHaveAttribute("href", "/datasets/d1?tab=grading");
  expect(
    within(warning).getByText(/Phrase each criterion as a yes\/no question/),
  ).toBeInTheDocument();
  expect(within(warning).getByRole("link", { name: "Choose the grading model" })).toHaveAttribute(
    "href",
    "/orgs/o1/members?tab=governance#org-grading-model",
  );
});

it("falls back to the newest plain test, and offers testing again", async () => {
  state.kept = [evalRun({ id: "plain", dataset_id: "d1", purpose: "manual" })];
  state.run = finished();
  useOrgStore.setState({ activeOrgId: null });
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByText("Today the agent handles 9 of 12 questions well.")).toBeInTheDocument();
  expect(screen.queryByText(/graded differently/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Test again" }));
  expect(await screen.findByRole("button", { name: BUTTON })).toBeInTheDocument();
  expect(state.estimate).toHaveBeenCalledWith(TWICE);
});

it("leaves out the grading model's link where no organization is active", () => {
  state.kept = [evalRun({ id: "steady", dataset_id: "d1", purpose: "stability" })];
  state.run = finished({ stability: { asked: 4, unstable: 2, noisy: true } });
  useOrgStore.setState({ activeOrgId: null });
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(within(screen.getByRole("alert")).getAllByRole("link")).toHaveLength(1);
});

it("says it is looking for an earlier test while the list loads", () => {
  state.keptLoading = true;
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("status")).toHaveTextContent(/Looking for an earlier test/);
  expect(state.estimate).not.toHaveBeenCalled();
});

it("does not call an unfinished or failed test a measurement", async () => {
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  await userEvent.click(await screen.findByRole("button", { name: BUTTON }));
  state.run = evalRun({ status: "failed" });
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/did not finish/);
  state.run = evalRun({ status: "completed", arms: [] });
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("alert")).toHaveTextContent(/did not finish/);
  state.error = new Error("Forbidden");
  view.rerender(<TodayCheck agentId="a1" datasetId="d1" />);
  expect(screen.getByRole("alert")).toHaveTextContent("Forbidden");
});

it("keeps a run started on another dataset to that dataset", async () => {
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  await userEvent.click(await screen.findByRole("button", { name: BUTTON }));
  view.rerender(<TodayCheck agentId="a1" datasetId="d2" />);
  expect(await screen.findByRole("button", { name: BUTTON })).toBeInTheDocument();
});

it("keeps an unaffordable test disabled and shows refusals", async () => {
  state.estimate.mockResolvedValue(estimate(12, "9", "1", false));
  const view = render(<TodayCheck agentId="a1" datasetId="d1" />);
  await screen.findByText(/12 questions/);
  expect(screen.getByRole("button", { name: BUTTON })).toBeDisabled();
  view.unmount();
  state.estimate.mockResolvedValue(estimate(12));
  state.start.mockRejectedValue(new Error("Budget refused"));
  render(<TodayCheck agentId="a1" datasetId="d1" />);
  await screen.findByText(/12 questions/);
  await userEvent.click(screen.getByRole("button", { name: BUTTON }));
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
  settle(estimate(1, "0"));
  let fail: (reason: unknown) => void = () => {};
  state.estimate.mockReturnValue(new Promise((_, reject) => (fail = reject)));
  const failed = render(<TodayCheck agentId="a1" datasetId="d3" />);
  failed.unmount();
  fail(new Error("late"));
  await Promise.resolve();
  expect(state.estimate).toHaveBeenCalledTimes(3);
});
