import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RoomMessageReactionsRead } from "@/types/room-message-reaction";
import { useRoomMessageReactions } from "./use-room-message-reactions";

const mocks = vi.hoisted(() => ({
  identity: {
    accountId: "user-1",
    organizationId: "org-1",
    tenant: "org-1",
    current: vi.fn(() => true),
  },
  setReaction: vi.fn(),
  removeReaction: vi.fn(),
  announce: vi.fn(),
}));

vi.mock("@/hooks/use-room", () => ({ useRoomIdentity: () => mocks.identity }));
vi.mock("@/lib/room-events", () => ({ announceRoomChange: mocks.announce }));
vi.mock("@/lib/room-message-reactions-api", () => ({
  setRoomMessageReaction: mocks.setReaction,
  removeRoomMessageReaction: mocks.removeReaction,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const initial = [{ emoji: "🎉", count: 1, reacted_by_me: false }];
const changed = [{ emoji: "👍", count: 2, reacted_by_me: true }];

beforeEach(() => {
  mocks.identity.accountId = "user-1";
  mocks.identity.organizationId = "org-1";
  mocks.identity.tenant = "org-1";
  mocks.identity.current.mockReturnValue(true);
  mocks.setReaction.mockReset();
  mocks.removeReaction.mockReset();
  mocks.announce.mockReset();
});

describe("useRoomMessageReactions", () => {
  it("ignores a deferred response after the component switches messages", async () => {
    const pendingResponse = deferred<RoomMessageReactionsRead>();
    mocks.setReaction.mockReturnValueOnce(pendingResponse.promise);
    const { result, rerender } = renderHook(
      ({ messageId, reactions }) => useRoomMessageReactions("conversation-1", messageId, reactions),
      { initialProps: { messageId: "message-1", reactions: initial } },
    );

    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.add("🔥");
    });
    expect(result.current.isPending).toBe(true);

    rerender({ messageId: "message-2", reactions: changed });
    expect(result.current.reactions).toEqual(changed);
    expect(result.current.isPending).toBe(false);
    expect(result.current.hasError).toBe(false);

    await act(async () => {
      pendingResponse.resolve({ reactions: initial });
      await pending;
    });

    expect(result.current.reactions).toEqual(changed);
    expect(result.current.hasError).toBe(false);
    expect(mocks.announce).not.toHaveBeenCalled();
  });

  it("ignores a deferred response after the active organization changes", async () => {
    const pendingResponse = deferred<RoomMessageReactionsRead>();
    mocks.setReaction.mockReturnValueOnce(pendingResponse.promise);
    const { result, rerender } = renderHook(() =>
      useRoomMessageReactions("conversation-1", "message-1", initial),
    );

    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.add("🔥");
    });
    mocks.identity.organizationId = "org-2";
    mocks.identity.tenant = "org-2";
    rerender();

    expect(result.current.isPending).toBe(false);
    expect(result.current.hasError).toBe(false);
    await act(async () => {
      pendingResponse.resolve({ reactions: changed });
      await pending;
    });
    expect(result.current.reactions).toEqual(initial);
    expect(mocks.announce).not.toHaveBeenCalled();
  });

  it("clears a failed retry when the component switches messages", async () => {
    mocks.setReaction.mockRejectedValueOnce(new Error("request failed"));
    const { result, rerender } = renderHook(
      ({ messageId, reactions }) => useRoomMessageReactions("conversation-1", messageId, reactions),
      { initialProps: { messageId: "message-1", reactions: initial } },
    );

    await act(async () => {
      expect(await result.current.add("🔥")).toBe(false);
    });
    expect(result.current.hasError).toBe(true);

    rerender({ messageId: "message-2", reactions: changed });
    expect(result.current.hasError).toBe(false);
    await act(async () => {
      expect(await result.current.retry()).toBe(false);
    });
    expect(mocks.setReaction).toHaveBeenCalledTimes(1);
  });

  it("rejects a same-tick conflicting mutation while one request is pending", async () => {
    const pendingResponse = deferred<RoomMessageReactionsRead>();
    mocks.setReaction.mockReturnValueOnce(pendingResponse.promise);
    const { result } = renderHook(() =>
      useRoomMessageReactions("conversation-1", "message-1", initial),
    );

    let first!: Promise<boolean>;
    let second!: Promise<boolean>;
    act(() => {
      first = result.current.add("👍");
      second = result.current.remove("👍");
    });
    await expect(second).resolves.toBe(false);
    expect(mocks.setReaction).toHaveBeenCalledTimes(1);
    expect(mocks.removeReaction).not.toHaveBeenCalled();

    await act(async () => {
      pendingResponse.resolve({ reactions: changed });
      await first;
    });
  });

  it("uses repeatable add and remove calls as desired-state operations", async () => {
    mocks.setReaction.mockResolvedValue({ reactions: changed });
    mocks.removeReaction.mockResolvedValue({ reactions: [] });
    const { result } = renderHook(() =>
      useRoomMessageReactions("conversation-1", "message-1", initial),
    );

    await act(async () => {
      expect(await result.current.add("👍")).toBe(true);
    });
    await act(async () => {
      expect(await result.current.add("👍")).toBe(true);
    });
    await act(async () => {
      expect(await result.current.remove("👍")).toBe(true);
    });
    await act(async () => {
      expect(await result.current.remove("👍")).toBe(true);
    });

    expect(mocks.setReaction).toHaveBeenNthCalledWith(1, "conversation-1", "message-1", "👍");
    expect(mocks.setReaction).toHaveBeenNthCalledWith(2, "conversation-1", "message-1", "👍");
    expect(mocks.removeReaction).toHaveBeenNthCalledWith(1, "conversation-1", "message-1", "👍");
    expect(mocks.removeReaction).toHaveBeenNthCalledWith(2, "conversation-1", "message-1", "👍");
  });
});
