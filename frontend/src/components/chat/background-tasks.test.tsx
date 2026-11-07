import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { BackgroundTasks, BackgroundTaskList } from "./background-tasks";
import type { ConversationTask } from "@/hooks/use-conversation-tasks";

const env = vi.hoisted(() => ({
  tasks: [] as ConversationTask[],
  stop: vi.fn(),
  error: null as Error | null,
  retry: vi.fn(),
}));
vi.mock("@/hooks/use-conversation-tasks", () => ({
  taskIsActive: (task: ConversationTask) =>
    ["queued", "running", "awaiting_approval", "awaiting_answer"].includes(task.status),
  useConversationTasks: () => ({
    data: env.tasks,
    error: env.error,
    refetch: env.retry,
    stop: { mutate: env.stop, isPending: false },
  }),
}));
const task: ConversationTask = {
  id: "task",
  source_conversation_id: "source",
  conversation_id: "child",
  agent_id: "agent",
  title: "Export bug",
  status: "running",
  delivery: "pending",
  run_id: "run",
  return_run_id: null,
  outcome: null,
  created_at: "2026-11-03T22:00:00Z",
};
beforeEach(() => {
  env.tasks = [];
  env.error = null;
  env.stop.mockReset();
  env.retry.mockReset();
});
it("keeps the conversation compact and opens or stops each independent topic", async () => {
  env.tasks = [task];
  render(<BackgroundTasks conversationId="source" />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Background topics/ }));
  expect(screen.getByRole("link")).toHaveAttribute("href", "/chat?id=child");
  await userEvent.click(screen.getByRole("button", { name: "Stop Export bug" }));
  expect(env.stop).toHaveBeenCalledWith("task");
});
it("keeps an interrupted result honest and does not offer to replay completed actions", () => {
  env.tasks = [{ ...task, status: "completed", delivery: "interrupted" }];
  render(<BackgroundTaskList tasks={env.tasks} stopping={false} onStop={env.stop} />);
  expect(screen.getByText(/Result delivery interrupted/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Stop Export bug" })).not.toBeInTheDocument();
});
it("shows an empty dashboard and an explicit retry after a failed read", async () => {
  const view = render(<BackgroundTasks conversationId={null} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  env.error = new Error("Offline");
  view.rerender(<BackgroundTasks conversationId={null} />);
  await userEvent.click(screen.getByRole("button", { name: "Reload background topics" }));
  expect(env.retry).toHaveBeenCalledOnce();
});
