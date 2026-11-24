import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { onRoomChange } from "@/lib/room-events";
import { useAuthStore, useConversationStore, useOrgStore } from "@/stores";
import { useRoomThreadActions } from "./use-room-thread-actions";

const api = vi.hoisted(() => ({
  followRoomThread: vi.fn(),
  markRoomThreadRead: vi.fn(),
  unfollowRoomThread: vi.fn(),
  updateRoomThreadState: vi.fn(),
}));
vi.mock("@/lib/room-api", () => api);

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useAuthStore.setState({
    user: {
      id: "me",
      email: "me@example.com",
      is_active: true,
      created_at: "2026-11-13T00:00:00Z",
    },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a" });
});
afterEach(() => client.clear());

describe("room thread actions", () => {
  it("runs each write, announces the change and reports success", async () => {
    for (const fn of Object.values(api)) fn.mockResolvedValue(undefined);
    const announced = vi.fn();
    const off = onRoomChange(announced);
    const { result } = renderHook(() => useRoomThreadActions("room-a", "root-1"), { wrapper });

    await act(async () => {
      expect(await result.current.updateState("close")).toBe(true);
      expect(await result.current.follow()).toBe(true);
      expect(await result.current.unfollow()).toBe(true);
      expect(await result.current.markRead("message-9")).toBe(true);
    });
    off();

    expect(api.updateRoomThreadState).toHaveBeenCalledWith("room-a", "root-1", "close");
    expect(api.followRoomThread).toHaveBeenCalledWith("room-a", "root-1");
    expect(api.unfollowRoomThread).toHaveBeenCalledWith("room-a", "root-1");
    expect(api.markRoomThreadRead).toHaveBeenCalledWith("room-a", "root-1", "message-9");
    expect(announced).toHaveBeenCalledTimes(4);
    expect(result.current.isPending).toBe(false);
    expect(result.current.isMarkingRead).toBe(false);
  });

  it("reports pending state while a write and a read mark are in flight", async () => {
    const write = deferred<void>();
    const read = deferred<void>();
    api.followRoomThread.mockReturnValueOnce(write.promise);
    api.markRoomThreadRead.mockReturnValueOnce(read.promise);
    const { result } = renderHook(() => useRoomThreadActions("room-a", "root-1"), { wrapper });

    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    act(() => {
      first = result.current.follow();
      second = result.current.markRead("m");
    });
    expect(result.current.isPending).toBe(true);
    expect(result.current.isMarkingRead).toBe(true);
    await act(async () => {
      write.resolve();
      read.resolve();
      await Promise.all([first, second]);
    });
    expect(result.current.isPending).toBe(false);
    expect(result.current.isMarkingRead).toBe(false);
  });

  it("does nothing when the room is no longer selected", async () => {
    const { result } = renderHook(() => useRoomThreadActions("room-a", "root-1"), { wrapper });
    act(() => useConversationStore.setState({ currentConversationId: "room-b" }));
    await act(async () => {
      expect(await result.current.follow()).toBe(false);
    });
    expect(api.followRoomThread).not.toHaveBeenCalled();
  });

  it("drops a success that arrives after the room changed", async () => {
    const response = deferred<void>();
    api.followRoomThread.mockReturnValueOnce(response.promise);
    const announced = vi.fn();
    const off = onRoomChange(announced);
    const { result } = renderHook(() => useRoomThreadActions("room-a", "root-1"), { wrapper });

    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.follow();
    });
    useConversationStore.setState({ currentConversationId: "room-b" });
    await act(async () => {
      response.resolve();
      expect(await pending).toBe(false);
    });
    off();
    expect(announced).not.toHaveBeenCalled();
    expect(result.current.isPending).toBe(false);
  });

  it("surfaces a failure, but drops one that arrives after the room changed", async () => {
    api.followRoomThread.mockRejectedValueOnce(new Error("refused"));
    const { result } = renderHook(() => useRoomThreadActions("room-a", "root-1"), { wrapper });
    await act(async () => {
      await expect(result.current.follow()).rejects.toThrow("refused");
    });

    const response = deferred<void>();
    api.unfollowRoomThread.mockReturnValueOnce(response.promise);
    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.unfollow();
    });
    useConversationStore.setState({ currentConversationId: "room-b" });
    await act(async () => {
      response.reject(new Error("late"));
      expect(await pending).toBe(false);
    });
  });
});
