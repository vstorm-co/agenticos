import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useConversationTasks, type ConversationTask } from "@/hooks/use-conversation-tasks";
import { WorkspaceTasksPanel } from "./workspace-tasks-panel";

const state = vi.hoisted(() => ({
  data: [] as ConversationTask[] | undefined,
  isPending: false,
  error: null as Error | null,
  refetch: vi.fn(),
  stop: { mutate: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-conversation-tasks", async (original) => ({
  ...(await original<typeof import("@/hooks/use-conversation-tasks")>()),
  useConversationTasks: vi.fn(() => state),
}));
const task = (status: ConversationTask["status"], title: string = status): ConversationTask => ({
  id: status,
  source_conversation_id: "source",
  conversation_id: `topic-${status}`,
  agent_id: "agent",
  title,
  status,
  delivery: "pending",
  run_id: null,
  return_run_id: null,
  outcome: null,
  created_at: "2026-11-17T00:00:00Z",
});
const props = () => ({
  panelId: "tasks-panel",
  conversationId: "source",
  readOnly: false,
  onClose: vi.fn(),
});
beforeEach(() => {
  vi.clearAllMocks();
  state.data = [];
  state.isPending = false;
  state.error = null;
  state.stop.isPending = false;
});

it("opens the current chat's tasks and can switch to the member's cross-agent work", async () => {
  state.data = [task("running", "Research")];
  render(<WorkspaceTasksPanel {...props()} />);
  expect(useConversationTasks).toHaveBeenLastCalledWith("source");
  expect(screen.getByRole("complementary", { name: "Tasks" })).toHaveAttribute("id", "tasks-panel");
  expect(screen.getByRole("link", { name: /Research/ })).toHaveAttribute(
    "href",
    "/chat?id=topic-running",
  );
  await userEvent.click(screen.getByRole("button", { name: "All my tasks" }));
  expect(useConversationTasks).toHaveBeenLastCalledWith(null);
  expect(screen.getByRole("button", { name: "All my tasks" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await userEvent.click(screen.getByRole("button", { name: "This chat" }));
  expect(useConversationTasks).toHaveBeenLastCalledWith("source");
  expect(state.stop.mutate).not.toHaveBeenCalled();
});

it("lists the member's tasks from a new chat without pretending that it has a saved ID", () => {
  render(<WorkspaceTasksPanel {...props()} conversationId={null} />);
  expect(useConversationTasks).toHaveBeenLastCalledWith(null);
  expect(screen.getByRole("button", { name: "This chat" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("No background tasks yet");
});

it("groups every task status without concealing failed or interrupted work", () => {
  state.data = [
    "awaiting_approval",
    "awaiting_answer",
    "running",
    "queued",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
  ].map((status) => task(status as ConversationTask["status"]));
  render(<WorkspaceTasksPanel {...props()} />);
  expect(
    within(screen.getByRole("region", { name: "Needs you (2)" })).getAllByRole("link"),
  ).toHaveLength(2);
  expect(
    within(screen.getByRole("region", { name: "Working (1)" })).getAllByRole("link"),
  ).toHaveLength(1);
  expect(
    within(screen.getByRole("region", { name: "Waiting (1)" })).getAllByRole("link"),
  ).toHaveLength(1);
  expect(
    within(screen.getByRole("region", { name: "Finished (4)" })).getAllByRole("link"),
  ).toHaveLength(4);
  expect(screen.getAllByRole("button", { name: /^Stop / })).toHaveLength(4);
});

it("filters titles without changing task scope or sending anything", async () => {
  state.data = [task("running", "Inventory report"), task("queued", "Supplier research")];
  render(<WorkspaceTasksPanel {...props()} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search tasks" }), " INVENTORY ");
  expect(screen.getByRole("link", { name: /Inventory report/ })).toBeVisible();
  expect(screen.queryByRole("link", { name: /Supplier research/ })).toBeNull();
  expect(screen.queryByRole("region", { name: /Waiting/ })).toBeNull();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "missing" } });
  expect(screen.getByRole("status")).toHaveTextContent("No tasks match your search");
  expect(state.stop.mutate).not.toHaveBeenCalled();
});

it("stops only a deliberately selected active task and blocks duplicate pending stops", async () => {
  state.data = [task("running", "Research")];
  const view = render(<WorkspaceTasksPanel {...props()} />);
  await userEvent.click(screen.getByRole("button", { name: "Stop Research" }));
  expect(state.stop.mutate).toHaveBeenCalledExactlyOnceWith("running");
  state.stop.isPending = true;
  view.rerender(<WorkspaceTasksPanel {...props()} />);
  expect(screen.getByRole("button", { name: "Stop Research" })).toBeDisabled();
});

it("keeps task navigation available in a read-only chat and hides stop actions", () => {
  state.data = [task("running", "Research")];
  render(<WorkspaceTasksPanel {...props()} readOnly />);
  expect(screen.getByRole("link", { name: /Research/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Stop Research" })).toBeNull();
  expect(state.stop.mutate).not.toHaveBeenCalled();
});

it("distinguishes a pending read, a refused read and a real empty list", async () => {
  state.isPending = true;
  state.data = undefined;
  const options = props();
  const view = render(<WorkspaceTasksPanel {...options} />);
  expect(screen.getByRole("status")).toHaveTextContent(/Loading/);
  state.isPending = false;
  state.error = new Error("Unavailable");
  view.rerender(<WorkspaceTasksPanel {...options} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Tasks could not be loaded");
  expect(screen.queryByText(/No background tasks yet/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
  state.error = null;
  state.data = [];
  view.rerender(<WorkspaceTasksPanel {...options} />);
  expect(screen.getByRole("status")).toHaveTextContent("No background tasks yet");
});

it("supports expansion, clears search on Escape, then closes and restores focus", async () => {
  const options = props();
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const view = render(<WorkspaceTasksPanel {...options} />);
  expect(screen.getByRole("button", { name: "Close tasks" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Expand tasks" }));
  expect(screen.getByRole("complementary")).toHaveAttribute("data-browser-panel", "fullscreen");
  await userEvent.click(screen.getByRole("button", { name: "Restore tasks" }));
  expect(screen.getByRole("complementary")).toHaveAttribute("data-browser-panel", "docked");
  await userEvent.type(screen.getByRole("searchbox"), "draft");
  fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" });
  expect(screen.getByRole("searchbox")).toHaveValue("");
  expect(options.onClose).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" });
  expect(options.onClose).toHaveBeenCalledOnce();
  expect(opener).toHaveFocus();
  view.unmount();
  opener.remove();
});

it("closes from its explicit close button", async () => {
  const options = props();
  render(<WorkspaceTasksPanel {...options} />);
  await userEvent.click(screen.getByRole("button", { name: "Close tasks" }));
  expect(options.onClose).toHaveBeenCalledOnce();
});

it("closes safely when the original workspace control no longer exists", async () => {
  const options = props();
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  render(<WorkspaceTasksPanel {...options} />);
  opener.remove();
  await userEvent.click(screen.getByRole("button", { name: "Close tasks" }));
  expect(options.onClose).toHaveBeenCalledOnce();
});
