import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  useConversationTasks,
  taskIsActive,
  type ConversationTask,
} from "./use-conversation-tasks";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

const scope = vi.hoisted(() => ({ tenant: "org-1" as string | null }));
vi.mock("./use-organizations", () => ({
  useTenantId: () => scope.tenant,
  useTenantGuard: () => (startedIn: string | null) => startedIn === scope.tenant,
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const user = {
  id: "person-1",
  email: "person@example.test",
  is_active: true,
  created_at: "2026-11-03",
};
beforeEach(() => {
  vi.clearAllMocks();
  scope.tenant = "org-1";
  useAuthStore.setState({ user });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  vi.mocked(apiClient.get).mockResolvedValue([]);
  vi.mocked(apiClient.post).mockResolvedValue({});
});

it("waits for a saved chat, resolved tenant and signed-in person", () => {
  renderHook(() => useConversationTasks(undefined), { wrapper });
  scope.tenant = null;
  renderHook(() => useConversationTasks("chat"), { wrapper });
  scope.tenant = "org-1";
  useAuthStore.setState({ user: null });
  renderHook(() => useConversationTasks("chat"), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("asks only for the opened source conversation, with an abort signal", async () => {
  const { result } = renderHook(() => useConversationTasks("chat"), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(apiClient.get).toHaveBeenCalledWith("/conversations/background-tasks", {
    signal: expect.any(AbortSignal),
    params: { conversation_id: "chat" },
  });
  expect(client.getQueryData(qk.conversationTasks.list("person-1:org-1", "chat"))).toEqual([]);
});

it("lists the person's tasks across topics for the dashboard", async () => {
  const { result } = renderHook(() => useConversationTasks(null), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(apiClient.get).toHaveBeenCalledWith("/conversations/background-tasks", {
    signal: expect.any(AbortSignal),
    params: {},
  });
});

it("stops the requested task and invalidates the person's task queries", async () => {
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useConversationTasks("chat"), { wrapper });
  await act(() => result.current.stop.mutateAsync("task/1"));
  expect(apiClient.post).toHaveBeenCalledWith("/conversations/background-tasks/task%2F1/stop");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.conversationTasks.all("person-1:org-1") });
});

it("shows a stop refusal to the person who requested it", async () => {
  vi.mocked(apiClient.post).mockRejectedValue(new Error("refused"));
  const { result } = renderHook(() => useConversationTasks("chat"), { wrapper });
  await act(() => result.current.stop.mutateAsync("task").catch(() => undefined));
  expect(toast.error).toHaveBeenCalledOnce();
});

it.each(["tenant", "person"])(
  "drops a late stop completion after the %s changes",
  async (changed) => {
    let finish!: (value: object) => void;
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useConversationTasks("chat"), { wrapper });
    let pending: Promise<unknown>;
    act(() => {
      pending = result.current.stop.mutateAsync("task");
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledOnce());
    if (changed === "tenant") scope.tenant = "other-org";
    else act(() => useAuthStore.setState({ user: { ...user, id: "other-person" } }));
    await act(async () => {
      finish({});
      await pending;
    });
    expect(invalidate).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  },
);

it("suppresses an old tenant's stop error after switching organizations", async () => {
  let fail!: (reason: Error) => void;
  vi.mocked(apiClient.post).mockReturnValue(
    new Promise((_resolve, reject) => {
      fail = reject;
    }),
  );
  const { result } = renderHook(() => useConversationTasks("chat"), { wrapper });
  let pending: Promise<unknown>;
  act(() => {
    pending = result.current.stop.mutateAsync("task").catch(() => undefined);
  });
  await waitFor(() => expect(apiClient.post).toHaveBeenCalledOnce());
  scope.tenant = "other-org";
  await act(async () => {
    fail(new Error("refused"));
    await pending;
  });
  expect(toast.error).not.toHaveBeenCalled();
});

it("polls active tasks and slows down once all of them finish", async () => {
  const task: ConversationTask = {
    id: "task",
    source_conversation_id: "source",
    conversation_id: "child",
    agent_id: "agent",
    title: "Research",
    status: "running",
    delivery: "pending",
    run_id: null,
    return_run_id: null,
    outcome: null,
    created_at: "2026-11-03",
  };
  vi.mocked(apiClient.get).mockResolvedValue([task]);
  const { result } = renderHook(() => useConversationTasks("source"), { wrapper });
  await waitFor(() => expect(result.current.data).toHaveLength(1));
  expect(taskIsActive(task)).toBe(true);
  vi.mocked(apiClient.get).mockResolvedValue([{ ...task, status: "completed" }]);
  await act(async () => {
    await result.current.refetch();
  });
  await waitFor(() => expect(result.current.data?.some(taskIsActive)).toBe(false));
});

it("suppresses an old person's stop error after switching accounts", async () => {
  vi.mocked(apiClient.post).mockImplementation(async () => {
    useAuthStore.setState({ user: { ...user, id: "different-person" } });
    throw new Error("refused");
  });
  const { result } = renderHook(() => useConversationTasks("source"), { wrapper });
  await act(() => result.current.stop.mutateAsync("task").catch(() => undefined));
  expect(toast.error).not.toHaveBeenCalled();
});
