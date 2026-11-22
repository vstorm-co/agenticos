import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import type { AgentRun } from "@/types/runs";
import { AgentRecentWork } from "./agent-recent-work";

const useRuns = vi.fn();
const refetch = vi.fn();
vi.mock("@/hooks/use-runs", () => ({ useRuns: (id: string) => useRuns(id) }));

function run(id: string, status: AgentRun["status"]): AgentRun {
  return {
    id,
    status,
    agent_id: "a1",
    agent_version_id: null,
    user_id: null,
    surface: "web",
    model_label: null,
    provider: null,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: "0",
    cost_is_partial: false,
    logfire_trace_id: null,
    error: null,
    down_rated: false,
    conversation_id: null,
    modality: "text",
    voice_chain: null,
    started_at: null,
    ended_at: null,
    parent_run_id: null,
    subagent_task_id: null,
    preview: `Task ${id}`,
  };
}
function draw() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <AgentRecentWork agentId="a1" />
    </NextIntlClientProvider>,
  );
}
beforeEach(() => {
  useRuns.mockReturnValue({ runs: [], isLoading: false, error: null, refetch });
  refetch.mockClear();
});

it("surfaces attention among the latest three without presenting old failures as current work", () => {
  useRuns.mockReturnValue({
    runs: [
      run("latest", "completed"),
      run("waiting", "awaiting_approval"),
      run("third", "running"),
      run("old", "failed"),
    ],
  });
  draw();
  expect(useRuns).toHaveBeenCalledWith("a1");
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", "/runs?agent=a1&run=waiting");
  expect(rows).toHaveLength(3);
  expect(screen.queryByText("Task old")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Run history" })).toHaveAttribute(
    "href",
    "/runs?agent=a1",
  );
});
it("distinguishes an unread history from no work and offers a retry", async () => {
  useRuns.mockReturnValue({ runs: [], isLoading: false, error: new Error("offline"), refetch });
  draw();
  expect(screen.getByText("Run history could not be read")).toBeVisible();
  expect(screen.queryByText("Nobody has run anything yet.")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(refetch).toHaveBeenCalledOnce();
});
it("has an honest empty state without fabricated activity or metrics", () => {
  draw();
  expect(screen.getByText("Nobody has run anything yet.")).toBeVisible();
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
});
