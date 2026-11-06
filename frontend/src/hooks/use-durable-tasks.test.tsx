import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { useOrgStore } from "@/stores";
import { useAuthStore } from "@/stores/auth-store";
import * as tasks from "@/lib/tasks-api";
import { useDurableTasks } from "./use-durable-tasks";
vi.mock("@/lib/tasks-api", () => ({
  listTaskBoards: vi.fn(),
  listDurableTasks: vi.fn(),
  ensureTaskBoard: vi.fn(),
  createDurableTask: vi.fn(),
  updateDurableTask: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useOrgStore.setState({ activeOrgId: "org" });
  useAuthStore.setState({
    user: { id: "person", email: "person@example.com", is_active: true, created_at: "2026-11-01" },
  });
  vi.mocked(tasks.listTaskBoards).mockResolvedValue([]);
  vi.mocked(tasks.listDurableTasks).mockResolvedValue({ items: [], has_more: false });
});
it("keeps table pagination and refreshes the current tenant after ensuring a board", async () => {
  const invalidate = vi.spyOn(client, "invalidateQueries");
  vi.mocked(tasks.ensureTaskBoard).mockResolvedValue({
    id: "board",
    scope_kind: "private",
    scope_name: null,
    can_edit: true,
    scope_id: "person",
    table_id: "table",
  });
  const { result } = renderHook(() => useDurableTasks("table", 50), { wrapper });
  await waitFor(() => expect(result.current.records.isSuccess).toBe(true));
  expect(tasks.listDurableTasks).toHaveBeenCalledWith("table", 50, expect.any(AbortSignal));
  await act(() => result.current.ensure.mutateAsync({ kind: "private" }));
  expect(invalidate).toHaveBeenCalled();
  vi.mocked(tasks.ensureTaskBoard).mockRejectedValue(new Error("Table limit reached"));
  await act(async () => {
    await result.current.ensure.mutateAsync({ kind: "private" }).catch(() => undefined);
  });
  expect(toast.error).toHaveBeenCalled();
});

it("updates a record using its current revision and shows a refused update", async () => {
  const task: tasks.DurableTask = {
    id: "task",
    table_id: "table",
    board_id: "board",
    scope: "private",
    scope_id: "person",
    title: "Review",
    description: "Notes",
    status: "planned",
    assignee_user_id: "person",
    assignee_agent_id: null,
    next_actor: "user",
    due_at: null,
    start_at: null,
    revision: 2,
    conversation_id: null,
    outcome_id: null,
    created_at: "2026-11-01",
  };
  vi.mocked(tasks.updateDurableTask).mockResolvedValue({ ...task, status: "done" });
  const { result } = renderHook(() => useDurableTasks("table"), { wrapper });
  await act(() => result.current.update.mutateAsync({ task, status: "done" }));
  expect(tasks.updateDurableTask).toHaveBeenCalledWith(task, "done");
  vi.mocked(tasks.updateDurableTask).mockRejectedValue(new Error("Task changed"));
  await act(async () => {
    await result.current.update.mutateAsync({ task, status: "blocked" }).catch(() => undefined);
  });
  expect(toast.error).toHaveBeenCalled();
});
