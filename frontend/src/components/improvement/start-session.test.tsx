import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useOrgStore } from "@/stores/org-store";
import { StartSession } from "./start-session";

const state = vi.hoisted(() => ({
  estimate: vi.fn(),
  start: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  params: new URLSearchParams(),
  sessionError: null as Error | null,
  datasetError: null as Error | null,
  testSetLoading: false,
  own: [{ id: "own", name: "Refund desk - test questions", can_run: true }] as {
    id: string;
    name: string;
    can_run: boolean;
    agent_id?: string | null;
  }[],
  sessions: [] as { id: string; created_at: string; status: string }[],
  datasetQueries: [] as unknown[],
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, replace: state.replace }),
  useSearchParams: () => state.params,
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: (query: { agent?: string }) => {
    state.datasetQueries.push(query);
    return query.agent
      ? { datasets: state.own, isLoading: state.testSetLoading, error: null }
      : {
          error: state.datasetError,
          datasets: [
            { id: "d1", name: "Refund questions", can_run: true },
            { id: "forbidden", name: "Cannot run", can_run: false },
          ],
        };
  },
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovements: () => ({
    sessions: state.sessions,
    error: state.sessionError,
    estimate: { mutateAsync: state.estimate },
    start: { mutateAsync: state.start, isPending: false },
  }),
}));
vi.mock("./write-questions", () => ({
  WriteQuestions: ({ onReady }: { onReady: (id: string) => void }) => (
    <button onClick={() => onReady("written")}>Write test questions for me</button>
  ),
}));
vi.mock("./today-check", () => ({
  TodayCheck: ({ datasetId }: { datasetId: string }) => <p>Today on {datasetId}</p>,
}));
vi.mock("./session-inputs", () => ({ StartSignals: () => null }));
vi.mock("@/components/agents/system-agent-choice", () => ({
  SystemAgentChoice: ({
    onChange,
    wizard,
  }: {
    onChange: (value: string) => void;
    wizard?: boolean;
  }) => <button onClick={() => onChange("h1")}>{wizard ? "Use custom helper" : "Wrong"}</button>,
}));

const QUOTE = {
  total_usd: "0.12",
  cases: 12,
  max_iterations: 3,
  evidence_runs: 5,
  estimated_minutes: 4,
  affordable: true,
  reason: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  state.params = new URLSearchParams();
  state.sessionError = state.datasetError = null;
  state.testSetLoading = false;
  state.own = [{ id: "own", name: "Refund desk - test questions", can_run: true }];
  state.sessions = [];
  state.datasetQueries = [];
  state.estimate.mockResolvedValue(QUOTE);
  state.start.mockResolvedValue({ id: "s1" });
});

it("prices the agent's own test set at once, so Start improving is the one decision", async () => {
  render(<StartSession agentId="a1" />);
  expect(state.datasetQueries).toContainEqual({ agent: "a1", sort: "updated", limit: 5 });
  expect(
    await screen.findByText(/About 4 minutes, up to.*0\.12.*\(estimate\)/),
  ).toBeInTheDocument();
  expect(state.estimate).toHaveBeenCalledWith({ dataset_id: "own", max_iterations: 3 });
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start improving" }));
  expect(state.start).toHaveBeenCalledWith({
    dataset_id: "own",
    max_iterations: 3,
    budget_usd: "0.12",
  });
  expect(state.push).toHaveBeenCalledWith("/agents/a1/improve/s1");
});

it("keeps the question set, the limit, the helper and today's test under Show details", async () => {
  render(<StartSession agentId="a1" />);
  await screen.findByRole("button", { name: "Start improving" });
  const details = screen.getByText("Show details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(details).toContainElement(screen.getByRole("combobox", { name: "Test questions" }));
  expect(details).toContainElement(screen.getByLabelText("Session spending limit (USD)"));
  expect(details).not.toContainElement(screen.getByRole("button", { name: "Start improving" }));
  expect(screen.queryByText("Today on own")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("Show details"));
  expect(await screen.findByText("Today on own")).toBeInTheDocument();
});

it("prices another question set, a lower limit and another helper when they are chosen", async () => {
  render(<StartSession agentId="a1" />);
  await screen.findByRole("button", { name: "Start improving" });
  await userEvent.click(screen.getByText("Show details"));
  await userEvent.click(screen.getByRole("combobox", { name: "Test questions" }));
  expect(screen.queryByRole("option", { name: "Cannot run" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Refund questions" }));
  await userEvent.click(screen.getByRole("button", { name: "Use custom helper" }));
  expect(state.estimate).toHaveBeenLastCalledWith({
    dataset_id: "d1",
    improver_agent_id: "h1",
    max_iterations: 3,
  });
  const limit = await screen.findByLabelText("Session spending limit (USD)");
  await userEvent.clear(limit);
  expect(screen.getByRole("button", { name: "Start improving" })).toBeDisabled();
  await userEvent.type(limit, "0.05");
  await userEvent.click(screen.getByRole("button", { name: "Start improving" }));
  expect(state.start).toHaveBeenCalledWith(
    expect.objectContaining({ dataset_id: "d1", budget_usd: "0.05" }),
  );
});

it("writes test questions for an agent without any, then prices the session on them", async () => {
  state.own = [];
  render(<StartSession agentId="a1" />);
  expect(state.estimate).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Write test questions for me" }));
  expect(await screen.findByRole("button", { name: "Start improving" })).toBeInTheDocument();
  expect(state.estimate).toHaveBeenCalledWith({ dataset_id: "written", max_iterations: 3 });
});

it("prefers the set made for the agent over one it was only tested on, and takes that otherwise", async () => {
  state.own = [
    { id: "guarded", name: "Guard questions", can_run: true, agent_id: null },
    { id: "made", name: "Refund desk - test questions", can_run: true, agent_id: "a1" },
  ];
  const view = render(<StartSession agentId="a1" />);
  await screen.findByRole("button", { name: "Start improving" });
  expect(state.estimate).toHaveBeenCalledWith({ dataset_id: "made", max_iterations: 3 });
  view.unmount();
  state.own = [{ id: "guarded", name: "Guard questions", can_run: true, agent_id: null }];
  render(<StartSession agentId="a1" />);
  await screen.findAllByRole("button", { name: "Start improving" });
  expect(state.estimate).toHaveBeenLastCalledWith({ dataset_id: "guarded", max_iterations: 3 });
});

it("waits for the agent's test set before offering to write one", () => {
  state.testSetLoading = true;
  state.own = [];
  render(<StartSession agentId="a1" />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading the result");
  expect(screen.queryByRole("button", { name: "Write test questions for me" })).toBeNull();
});

it("leads with today's test when it was opened to set a baseline", () => {
  state.params = new URLSearchParams("baseline=1");
  render(<StartSession agentId="a1" />);
  expect(screen.getByText(/Set a baseline/)).toBeInTheDocument();
  expect(screen.getByText("Today on own")).toBeInTheDocument();
});

it("starts from the question set a link names", async () => {
  state.params = new URLSearchParams("dataset=d1");
  render(<StartSession agentId="a1" />);
  await screen.findByRole("button", { name: "Start improving" });
  expect(state.estimate).toHaveBeenCalledWith({ dataset_id: "d1", max_iterations: 3 });
});

it("points to the one session still open instead of every past one", () => {
  state.sessions = [
    { id: "old", created_at: "2026-10-20T10:00:00Z", status: "published" },
    { id: "open", created_at: "2026-10-25T10:00:00Z", status: "ready" },
    { id: "older", created_at: "2026-10-21T10:00:00Z", status: "stopped" },
  ];
  render(<StartSession agentId="a1" />);
  const links = screen.getAllByRole("link", { name: /in progress/ });
  expect(links).toHaveLength(1);
  expect(links[0]).toHaveAttribute("href", "/agents/a1/improve/open");
});

it("says why an estimate or a read failed, without starting work", async () => {
  state.estimate.mockRejectedValueOnce(new Error("Estimate unavailable"));
  state.sessionError = new Error("Sessions unavailable");
  state.datasetError = new Error("Datasets unavailable");
  render(<StartSession agentId="a1" />);
  expect(await screen.findByText("Estimate unavailable")).toBeInTheDocument();
  expect(screen.getByText("Sessions unavailable")).toBeInTheDocument();
  expect(screen.getByText("Datasets unavailable")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start improving" })).toBeNull();
});

it("keeps the screen and says why when starting is refused", async () => {
  state.start.mockRejectedValueOnce(new Error("Budget refused"));
  render(<StartSession agentId="a1" />);
  await userEvent.click(await screen.findByRole("button", { name: "Start improving" }));
  expect(await screen.findByText("Budget refused")).toBeInTheDocument();
  expect(state.push).not.toHaveBeenCalled();
});

it("refuses an unaffordable session and names the reason", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, affordable: false, reason: "no_evidence" });
  render(<StartSession agentId="a1" />);
  expect(await screen.findByText(/Nothing to learn from yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start improving" })).toBeDisabled();
});

it("does not open a session in an organization the person has since left", async () => {
  render(<StartSession agentId="a1" />);
  const start = await screen.findByRole("button", { name: "Start improving" });
  state.start.mockImplementationOnce(async () => {
    useOrgStore.setState({ activeOrgId: "another" });
    return { id: "s1" };
  });
  await userEvent.click(start);
  expect(state.push).not.toHaveBeenCalled();
});

it("says what sorting the answers and drafting knowledge adds to the estimate", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, knowledge_usd: "0.02" });
  render(<StartSession agentId="a1" />);
  expect(await screen.findByText(/sorting the source answers/)).toBeInTheDocument();
});

it("drops an estimate or a refusal that arrives after the screen is gone", async () => {
  let settle: (value: unknown) => void = () => {};
  state.estimate.mockReturnValueOnce(new Promise((resolve) => (settle = resolve)));
  render(<StartSession agentId="a1" />).unmount();
  settle(QUOTE);
  let fail: (reason: unknown) => void = () => {};
  state.estimate.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
  render(<StartSession agentId="a1" />).unmount();
  fail(new Error("late"));
  await Promise.resolve();
  expect(state.estimate).toHaveBeenCalledTimes(2);
});

it("stays on a new session when the agent's last one was kept as a draft", () => {
  state.sessions = [{ id: "kept", created_at: "2026-10-25T10:00:00Z", status: "accepted" }];
  state.params = new URLSearchParams("resume=1");
  render(<StartSession agentId="a1" />);
  expect(state.replace).not.toHaveBeenCalled();
});

it("forwards a link to Improve to the session still open, and only a link", () => {
  state.sessions = [{ id: "open", created_at: "2026-10-25T10:00:00Z", status: "ready" }];
  const view = render(<StartSession agentId="a1" />);
  expect(state.replace).not.toHaveBeenCalled();
  view.unmount();
  state.params = new URLSearchParams("resume=1");
  render(<StartSession agentId="a1" />);
  expect(state.replace).toHaveBeenCalledWith("/agents/a1/improve/open");
});
