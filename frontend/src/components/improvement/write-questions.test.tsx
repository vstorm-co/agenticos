import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { AgentTestSetBootstrap } from "@/types/agent-test-set";
import { WriteQuestions } from "./write-questions";

const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  build: vi.fn(),
  generations: [] as { id: string; status: string }[],
  enabled: [] as boolean[],
}));
vi.mock("@/hooks/use-agent-test-set", () => ({
  useAgentTestSet: () => ({
    estimate: { mutateAsync: state.estimate },
    build: { mutateAsync: state.build, isPending: false },
  }),
}));
vi.mock("@/hooks/use-case-generation", () => ({
  useCaseGenerations: (_id: string, { enabled }: { enabled: boolean }) => {
    state.enabled.push(enabled);
    return { generations: state.generations };
  },
}));

const BUILT: AgentTestSetBootstrap = {
  dataset_id: "d1",
  version: 2,
  created: true,
  counts: { rated_good: 4, rated_bad: 3, skipped: 0, from_others: 0, generated_requested: 5 },
  generation_id: "g1",
  generation_skipped: null,
  judge: { agent_id: null, independent: false, reason: "One model", reason_code: "one_model" },
  gradable: 7,
  too_few: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  state.generations = [];
  state.enabled = [];
  state.estimate.mockResolvedValue({ cost_usd: "0.02", priced: true, generate: 12 });
  state.build.mockResolvedValue(BUILT);
});

it("prices writing the questions, writes them and waits for the generator", async () => {
  const ready = vi.fn();
  const view = render(<WriteQuestions agentId="a1" onReady={ready} />);
  expect(
    await screen.findByText(/Up to 12 questions written, about .*0\.02.*\(estimate\)/),
  ).toBeInTheDocument();
  expect(state.estimate).toHaveBeenCalledWith({});
  await userEvent.click(screen.getByRole("button", { name: "Write test questions for me" }));
  expect(state.build).toHaveBeenCalledWith({});
  expect(
    screen.getByText(
      "3 from answers people rated down, 4 from answers they liked, 5 being written for topics with no example.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/Writing the questions/)).toBeInTheDocument();
  expect(screen.getByText(/only one model is set up/)).toBeInTheDocument();
  expect(ready).not.toHaveBeenCalled();
  state.generations = [{ id: "g1", status: "ready" }];
  view.rerender(<WriteQuestions agentId="a1" onReady={ready} />);
  expect(screen.getByText("The questions are ready.")).toBeInTheDocument();
  expect(ready).toHaveBeenCalledWith("d1");
});

it("asks for a given number more and reports a failed or skipped writer", async () => {
  state.build.mockResolvedValue({
    ...BUILT,
    generation_id: null,
    generation_skipped: "ai_off",
    too_few: true,
    judge: { ...BUILT.judge, reason_code: "something_new" },
  });
  const ready = vi.fn();
  render(<WriteQuestions agentId="a1" more={6} onReady={ready} />);
  await userEvent.click(await screen.findByRole("button", { name: "Write 6 more" }));
  expect(state.build).toHaveBeenCalledWith({ more: 6 });
  expect(screen.getByText(/AI assistance is off/)).toBeInTheDocument();
  expect(screen.getByText(/Too few questions to measure a change/)).toBeInTheDocument();
  expect(ready).toHaveBeenCalledWith("d1");
  expect(state.enabled).toContain(false);
});

it("says when writing more questions failed", async () => {
  state.generations = [{ id: "g1", status: "failed" }];
  render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Write test questions for me" }));
  expect(screen.getByText(/Writing more questions failed/)).toBeInTheDocument();
});

it("refuses an unpriced writer and shows refusals", async () => {
  state.estimate.mockResolvedValue({ cost_usd: "0", priced: false, generate: 12 });
  const view = render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  expect(await screen.findByText(/can't be priced/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Write test questions for me" })).toBeDisabled();
  view.unmount();
  state.estimate.mockRejectedValue(new Error("No access"));
  render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("No access");
});

it("keeps the offer and says why when writing is refused", async () => {
  state.build.mockRejectedValue(new Error("Role may not create datasets"));
  render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Write test questions for me" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Role may not create datasets");
});

it("drops an estimate that arrives after the offer is gone", async () => {
  let settle: (value: unknown) => void = () => {};
  state.estimate.mockReturnValue(new Promise((resolve) => (settle = resolve)));
  const view = render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  view.unmount();
  settle({ cost_usd: "0.02", priced: true, generate: 12 });
  await Promise.resolve();
  let fail: (reason: unknown) => void = () => {};
  state.estimate.mockReturnValue(new Promise((_, reject) => (fail = reject)));
  const second = render(<WriteQuestions agentId="a1" onReady={vi.fn()} />);
  second.unmount();
  fail(new Error("late"));
  await Promise.resolve();
  expect(state.estimate).toHaveBeenCalledTimes(2);
});
