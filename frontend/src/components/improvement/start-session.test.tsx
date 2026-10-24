import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useOrgStore } from "@/stores/org-store";
import { StartSession } from "./start-session";
const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  start: vi.fn(),
  writeEstimate: vi.fn(),
  write: vi.fn(),
  sessionError: null as Error | null,
  datasetError: null as Error | null,
  sessions: [] as { id: string; created_at: string; status: string }[],
  built: null as { dataset_id: string } | null,
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: () => ({
    error: state.datasetError,
    datasets: [
      { id: "d1", name: "Refund questions", can_run: true },
      { id: "d2", name: "Other questions", can_run: true },
      { id: "forbidden", name: "Cannot run", can_run: false },
    ],
  }),
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovements: () => ({
    sessions: state.sessions,
    error: state.sessionError,
    estimate: { mutateAsync: state.estimate },
    start: { mutateAsync: state.start },
  }),
}));
vi.mock("@/hooks/use-agent-test-set", () => ({
  useAgentTestSet: () => ({
    estimate: { mutateAsync: state.writeEstimate },
    build: { mutateAsync: state.write, data: state.built },
  }),
}));
vi.mock("@/components/agents/system-agent-choice", () => ({
  SystemAgentChoice: ({ onChange }: { onChange: (value: string) => void }) => (
    <button onClick={() => onChange("h1")}>Use custom helper</button>
  ),
}));
vi.mock("@/components/evals/start-eval-dialog", () => ({
  StartEvalDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <div role="dialog">
      <button onClick={() => onOpenChange(false)}>Close baseline</button>
    </div>
  ),
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.sessionError = state.datasetError = null;
  state.sessions = [];
  state.built = null;
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

it("includes the separately estimated knowledge work before starting", async () => {
  state.estimate.mockResolvedValue({
    total_usd: "0.14",
    knowledge_usd: "0.02",
    cases: 12,
    max_iterations: 3,
    evidence_runs: 5,
    affordable: true,
    reason: null,
  });
  render(<StartSession agentId="a1" />);
  await userEvent.click(screen.getByRole("combobox", { name: "Test questions" }));
  await userEvent.click(screen.getByRole("option", { name: "Refund questions" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  expect(await screen.findByText(/Includes.*0.02.*sorting the source answers/)).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
});

async function selectQuestions() {
  await userEvent.click(screen.getByRole("combobox", { name: "Test questions" }));
  await userEvent.click(screen.getByRole("option", { name: "Refund questions" }));
}
it("keeps prior sessions and generated questions reachable even when fresh reads fail", () => {
  state.sessions = [{ id: "old", created_at: "2026-10-24T10:00:00Z", status: "ready" }];
  state.sessionError = new Error("Session read failed");
  state.datasetError = new Error("Questions read failed");
  state.built = { dataset_id: "d1" };
  render(<StartSession agentId="a1" />);
  expect(screen.getAllByRole("alert")).toHaveLength(2);
  expect(screen.getByRole("link", { name: /open session/ })).toHaveAttribute(
    "href",
    "/agents/a1/improve/old",
  );
  expect(screen.getByRole("link", { name: "Review the questions" })).toHaveAttribute(
    "href",
    "/datasets/d1",
  );
});
it("shows estimate errors without starting work", async () => {
  state.estimate.mockRejectedValue(new Error("Estimate unavailable"));
  render(<StartSession agentId="a1" />);
  await selectQuestions();
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
});
it("opens a baseline check, then invalidates the quote when the helper changes", async () => {
  render(<StartSession agentId="a1" />);
  await selectQuestions();
  await userEvent.click(screen.getByRole("button", { name: "Test how the agent answers today" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close baseline" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  await screen.findByRole("button", { name: "Start improving" });
  await userEvent.click(screen.getByRole("button", { name: "Use custom helper" }));
  expect(screen.queryByRole("button", { name: "Start improving" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  await screen.findByRole("button", { name: "Start improving" });
  expect(state.estimate).toHaveBeenLastCalledWith(
    expect.objectContaining({ improver_agent_id: "h1" }),
  );
  const budget = screen.getByRole("spinbutton");
  await userEvent.clear(budget);
  expect(screen.getByRole("button", { name: "Start improving" })).toBeDisabled();
  await userEvent.type(budget, "1");
  expect(screen.getByRole("button", { name: "Start improving" })).toBeEnabled();
});
it("refuses an unpriced generation and an unaffordable session", async () => {
  state.writeEstimate.mockResolvedValue({ cost_usd: "0", priced: false });
  state.estimate.mockResolvedValue({
    total_usd: "0.1",
    cases: 12,
    max_iterations: 3,
    evidence_runs: 0,
    affordable: false,
    reason: "no_evidence",
  });
  render(<StartSession agentId="a1" />);
  await userEvent.click(screen.getByText("Write test questions for me"));
  await userEvent.click(screen.getByRole("button", { name: "Estimate writing questions" }));
  expect(await screen.findByRole("button", { name: "Confirm and write questions" })).toBeDisabled();
  await selectQuestions();
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  expect(await screen.findByRole("button", { name: "Start improving" })).toBeDisabled();
});
it("does not navigate into an old organization after a delayed start response", async () => {
  state.start.mockImplementation(async () => {
    useOrgStore.setState({ activeOrgId: "other" });
    return { id: "late" };
  });
  render(<StartSession agentId="a1" />);
  await selectQuestions();
  await userEvent.click(screen.getByRole("button", { name: "Estimate the session" }));
  await userEvent.click(await screen.findByRole("button", { name: "Start improving" }));
  await waitFor(() => expect(state.start).toHaveBeenCalled());
});
