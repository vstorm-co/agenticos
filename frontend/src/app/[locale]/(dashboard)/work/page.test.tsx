import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ConversationTask } from "@/hooks/use-conversation-tasks";
import WorkPage from "./page";
vi.mock("@/components/tasks/tasks-panel", () => ({
  TasksPanel: () => <div data-testid="tasks" />,
}));
const state = vi.hoisted(() => ({ can: true, stop: vi.fn() }));
const task = (id: string, status: ConversationTask["status"]): ConversationTask => ({
  id,
  title: `Task ${id}`,
  status,
  conversation_id: `chat/${id}`,
  source_conversation_id: "source",
  agent_id: "agent",
  delivery: "pending",
  run_id: null,
  return_run_id: null,
  outcome: status === "completed" ? "Research result" : null,
  created_at: "2026-11-04T12:00:00Z",
});
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.can }) }));
vi.mock("@/hooks/use-conversation-tasks", async (original) => ({
  ...(await original<typeof import("@/hooks/use-conversation-tasks")>()),
  useConversationTasks: () => ({
    data: [task("active", "running"), task("done", "completed")],
    isPending: false,
    error: null,
    stop: { isPending: false, mutate: state.stop },
  }),
}));
describe("WorkPage", () => {
  it("separates ongoing tasks from results while preserving stop and conversation links", () => {
    render(<WorkPage />);
    expect(screen.getByRole("link", { name: "Task active" })).toHaveAttribute(
      "href",
      "/chat?id=chat%2Factive",
    );
    expect(screen.queryByText("Task done")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Stop.*Task active/ }));
    expect(state.stop).toHaveBeenCalledWith("active");
    fireEvent.click(screen.getByRole("button", { name: /History/ }));
    expect(screen.getByText("Research result")).toBeInTheDocument();
    expect(screen.queryByText("Task active")).toBeNull();
  });
  it("hides routine management from members without agent access", () => {
    state.can = false;
    render(<WorkPage />);
    expect(screen.queryByRole("link", { name: /Routines/ })).toBeNull();
  });
});
