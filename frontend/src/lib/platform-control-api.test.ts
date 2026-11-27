import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { updateDurableTask, type DurableTask } from "./tasks-api";
import { reviewDecisionCase } from "./memory-api";
vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
it("preserves rich notes, assignees, dates and optimistic revision when changing task status", async () => {
  const task: DurableTask = {
    id: "task",
    table_id: "table",
    board_id: "board",
    scope: "private",
    scope_id: "person",
    revision: 7,
    conversation_id: "chat",
    outcome_id: null,
    created_at: "2026-11-01",
    title: "Review draft",
    description: "**Notes**\n- [ ] Check",
    status: "planned",
    assignee_user_id: "person",
    assignee_agent_id: "agent",
    start_at: "2026-11-06T09:00:00Z",
    due_at: null,
    next_actor: "user",
  };
  await updateDurableTask(task, "done");
  expect(apiClient.put).toHaveBeenCalledWith("/tasks/task", {
    title: task.title,
    description: task.description,
    status: "done",
    assignee_user_id: "person",
    assignee_agent_id: "agent",
    next_actor: "user",
    start_at: task.start_at,
    due_at: null,
    expected_revision: 7,
  });
});
it("sends the explicitly reviewed decision answer rather than silently accepting a generated reference", async () => {
  await reviewDecisionCase("memory", "dataset", "Original question", "Corrected answer");
  expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/memory/improve-case", {
    confirmed: true,
    dataset_id: "dataset",
    input: "Original question",
    reference_answer: "Corrected answer",
  });
});
