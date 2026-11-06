import { apiClient } from "@/lib/api-client";

export type TaskScope = "private" | "project" | "group" | "organization";
export type TaskStatus =
  "planned" | "in_progress" | "waiting_for_user" | "blocked" | "done" | "cancelled";
export interface TaskBoard {
  id: string;
  scope_kind: TaskScope;
  scope_name: string | null;
  can_edit: boolean;
  scope_id: string;
  table_id: string;
}
export interface TaskFields {
  title: string;
  description: string;
  status: TaskStatus;
  assignee_user_id: string | null;
  assignee_agent_id: string | null;
  start_at: string | null;
  due_at: string | null;
  next_actor: "user" | "agent";
}
export interface DurableTask extends TaskFields {
  id: string;
  table_id: string;
  board_id: string;
  scope: TaskScope;
  scope_id: string;
  revision: number;
  conversation_id: string | null;
  outcome_id: string | null;
  created_at: string;
}
export interface TaskCreate extends TaskFields {
  scope: TaskScope;
  scope_id?: string;
}
export const listTaskBoards = (signal?: AbortSignal) =>
  apiClient.get<TaskBoard[]>("/tasks/boards", { signal });
export const ensureTaskBoard = (scope: TaskScope, scopeId?: string) =>
  apiClient.post<TaskBoard>("/tasks/boards", { scope, scope_id: scopeId });
export const listDurableTasks = (tableId: string, skip: number, signal?: AbortSignal) =>
  apiClient.get<{ items: DurableTask[]; has_more: boolean }>("/tasks", {
    signal,
    params: { table_id: tableId, skip: String(skip), limit: "50" },
  });
export const createDurableTask = (data: TaskCreate) => apiClient.post<DurableTask>("/tasks", data);
export const updateDurableTask = (task: DurableTask, status: TaskStatus) =>
  apiClient.put<DurableTask>(`/tasks/${task.id}`, {
    title: task.title,
    description: task.description,
    status,
    assignee_user_id: task.assignee_user_id,
    assignee_agent_id: task.assignee_agent_id,
    next_actor: task.next_actor,
    start_at: task.start_at,
    due_at: task.due_at,
    expected_revision: task.revision,
  });
