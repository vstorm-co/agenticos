import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { BackgroundTaskList } from "./background-tasks";
import type { ConversationTask } from "@/hooks/use-conversation-tasks";

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

it("opens and stops an active topic from the task list", async () => {
  const stop = vi.fn();
  render(<BackgroundTaskList tasks={[task]} stopping={false} onStop={stop} />);
  expect(screen.getByRole("link")).toHaveAttribute("href", "/chat?id=child");
  await userEvent.click(screen.getByRole("button", { name: "Stop Export bug" }));
  expect(stop).toHaveBeenCalledWith("task");
});

it("keeps an interrupted result honest and does not offer to replay completed actions", () => {
  const completed: ConversationTask = { ...task, status: "completed", delivery: "interrupted" };
  render(<BackgroundTaskList tasks={[completed]} stopping={false} onStop={vi.fn()} />);
  expect(screen.getByText(/Result delivery interrupted/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Stop Export bug" })).not.toBeInTheDocument();
});
