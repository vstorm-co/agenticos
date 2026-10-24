import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartSession } from "./start-session";
const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  start: vi.fn(),
  writeEstimate: vi.fn(),
  write: vi.fn(),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: () => ({
    datasets: [
      { id: "d1", name: "Refund questions", can_run: true },
      { id: "d2", name: "Other questions", can_run: true },
      { id: "forbidden", name: "Cannot run", can_run: false },
    ],
  }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovements: () => ({
    sessions: [],
    estimate: { mutateAsync: state.estimate },
    start: { mutateAsync: state.start },
  }),
}));
vi.mock("@/hooks/use-agent-test-set", () => ({
  useAgentTestSet: () => ({
    estimate: { mutateAsync: state.writeEstimate },
    build: { mutateAsync: state.write },
  }),
}));
vi.mock("@/components/agents/system-agent-choice", () => ({ SystemAgentChoice: () => null }));
vi.mock("@/components/evals/start-eval-dialog", () => ({ StartEvalDialog: () => null }));
beforeEach(() => {
  vi.clearAllMocks();
  state.estimate.mockResolvedValue({
    total_usd: "0.12",
    cases: 12,
    max_iterations: 3,
    evidence_runs: 5,
    affordable: true,
    reason: null,
  });
  state.start.mockResolvedValue({ id: "s1" });
});
it("shows a full estimate before the separate paid start with an explicit limit", async () => {
  render(<StartSession agentId="a1" />);
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("combobox", { name: "Test questions" }));
  expect(screen.queryByRole("option", { name: "Cannot run" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Refund questions" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  expect(await screen.findByText(/Up to.*0.12.*estimate/)).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start improving" }));
  expect(state.start).toHaveBeenCalledWith({
    dataset_id: "d1",
    max_iterations: 3,
    budget_usd: "0.12",
  });
});
it("invalidates an estimate when the question set changes", async () => {
  render(<StartSession agentId="a1" />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Refund questions" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  await screen.findByRole("button", { name: "Start improving" });
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Other questions" }));
  expect(screen.queryByRole("button", { name: "Start improving" })).not.toBeInTheDocument();
});
it("requires a price and another confirmation before writing questions", async () => {
  state.writeEstimate.mockResolvedValue({ cost_usd: "0.03", priced: true });
  state.write.mockResolvedValue({ dataset_id: "d1" });
  render(<StartSession agentId="a1" />);
  await userEvent.click(screen.getByText("Write test questions for me"));
  await userEvent.click(screen.getByRole("button", { name: "Estimate writing questions" }));
  expect(await screen.findByText(/Estimated cost:.*0.03/)).toBeInTheDocument();
  expect(state.write).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm and write questions" }));
  await waitFor(() => expect(state.write).toHaveBeenCalledWith({ more: 12 }));
});

vi.mock("./session-inputs", () => ({
  StartSignals: () => null,
  Understand: () => <p>Source examples fixture</p>,
  TestQuestions: () => <p>Pinned questions fixture</p>,
  Today: () => <p>Baseline fixture</p>,
}));
