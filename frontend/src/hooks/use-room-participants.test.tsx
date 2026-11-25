import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/types/conversation";
import type { CreateRoomConversationInput } from "@/types/room";
import {
  useAddRoomParticipant,
  useCreateRoomConversation,
  useJoinPublicRoom,
  useRemoveRoomParticipant,
  useRoomDirectory,
  useRoomMentionables,
  useRoomParticipants,
  useUpdateRoomAgentAutoReply,
} from "./use-room-participants";

const mocks = vi.hoisted(() => ({
  scope: { accountId: "user-1", organizationId: "org-1", tenant: "org-1" },
  createRoomConversation: vi.fn(),
  joinPublicRoom: vi.fn(),
  addRoomParticipant: vi.fn(),
  getRoomDirectory: vi.fn(),
  getRoomMentionables: vi.fn(),
  getRoomParticipants: vi.fn(),
  removeRoomParticipant: vi.fn(),
  updateRoomAgentAutoReply: vi.fn(),
}));

vi.mock("./use-room", () => ({
  useRoomIdentity: () => {
    const captured = { ...mocks.scope };
    const key = JSON.stringify(captured);
    return {
      ...captured,
      current: () => JSON.stringify(mocks.scope) === key,
    };
  },
}));
vi.mock("@/lib/room-api", () => ({
  addRoomParticipant: mocks.addRoomParticipant,
  createRoomConversation: mocks.createRoomConversation,
  getRoomDirectory: mocks.getRoomDirectory,
  getRoomMentionables: mocks.getRoomMentionables,
  getRoomParticipants: mocks.getRoomParticipants,
  joinPublicRoom: mocks.joinPublicRoom,
  removeRoomParticipant: mocks.removeRoomParticipant,
  updateRoomAgentAutoReply: mocks.updateRoomAgentAutoReply,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const conversation: Conversation = {
  id: "room-1",
  title: "Launch planning",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  is_archived: false,
  room_visibility: "public",
};

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  mocks.scope = { accountId: "user-1", organizationId: "org-1", tenant: "org-1" };
  mocks.createRoomConversation.mockReset();
  mocks.joinPublicRoom.mockReset();
  mocks.addRoomParticipant.mockReset();
  mocks.getRoomDirectory.mockReset();
  mocks.getRoomMentionables.mockReset();
  mocks.getRoomParticipants.mockReset();
  mocks.removeRoomParticipant.mockReset();
  mocks.updateRoomAgentAutoReply.mockReset();
});

describe("room create and join scope guards", () => {
  it("drops a public-room join response from the previous tenant", async () => {
    const response = deferred<Conversation>();
    mocks.joinPublicRoom.mockReturnValueOnce(response.promise);
    const { result, rerender } = renderHook(() => useJoinPublicRoom(), {
      wrapper: makeWrapper(),
    });

    let pending!: Promise<Conversation | null>;
    act(() => {
      pending = result.current.join("room-1");
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    rerender();

    await act(async () => {
      response.resolve(conversation);
      expect(await pending).toBeNull();
    });
    expect(mocks.joinPublicRoom).toHaveBeenCalledWith("room-1");
  });

  it("drops a room-create response from the previous tenant", async () => {
    const response = deferred<Conversation>();
    mocks.createRoomConversation.mockReturnValueOnce(response.promise);
    const { result, rerender } = renderHook(() => useCreateRoomConversation(), {
      wrapper: makeWrapper(),
    });

    let pending!: Promise<Conversation | null>;
    act(() => {
      pending = result.current.create({
        title: "Launch planning",
        visibility: "private",
        participants: [],
      });
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    rerender();

    await act(async () => {
      response.resolve(conversation);
      expect(await pending).toBeNull();
    });
    expect(mocks.createRoomConversation).toHaveBeenCalledWith({
      title: "Launch planning",
      visibility: "private",
      participants: [],
    });
  });
});

describe("room participant and directory queries", () => {
  it("exposes participants with their permissions", async () => {
    mocks.getRoomParticipants.mockResolvedValue({
      items: [{ kind: "user", id: "u1" }],
      visibility: "private",
      can_post: true,
      can_manage: true,
    });
    const { result } = renderHook(() => useRoomParticipants("room-1"), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.participants).toHaveLength(1);
    expect(result.current.visibility).toBe("private");
    expect(result.current.canPost).toBe(true);
    expect(result.current.canManage).toBe(true);
    expect(mocks.getRoomParticipants).toHaveBeenCalledWith("room-1");
  });

  it("stays idle and denies everything without a room", () => {
    const { result } = renderHook(() => useRoomParticipants(null), { wrapper: makeWrapper() });
    expect(result.current.participants).toEqual([]);
    expect(result.current.canPost).toBe(false);
    expect(result.current.canManage).toBe(false);
    expect(mocks.getRoomParticipants).not.toHaveBeenCalled();
  });

  it("does not query before the account and tenant are known", () => {
    mocks.scope = { accountId: undefined as never, organizationId: "org-1", tenant: null as never };
    renderHook(() => useRoomParticipants("room-1"), { wrapper: makeWrapper() });
    renderHook(() => useRoomMentionables("room-1"), { wrapper: makeWrapper() });
    renderHook(() => useRoomDirectory(), { wrapper: makeWrapper() });
    expect(mocks.getRoomParticipants).not.toHaveBeenCalled();
    expect(mocks.getRoomMentionables).not.toHaveBeenCalled();
    expect(mocks.getRoomDirectory).not.toHaveBeenCalled();
  });

  it("loads mentionables and reports their failure", async () => {
    mocks.getRoomMentionables.mockResolvedValueOnce({ items: [{ kind: "agent", id: "a1" }] });
    const ok = renderHook(() => useRoomMentionables("room-1"), { wrapper: makeWrapper() });
    await waitFor(() => expect(ok.result.current.mentionables).toHaveLength(1));

    mocks.getRoomMentionables.mockRejectedValueOnce(new Error("nope"));
    const bad = renderHook(() => useRoomMentionables("room-2"), { wrapper: makeWrapper() });
    await waitFor(() => expect(bad.result.current.error).toBeInstanceOf(Error));
    expect(bad.result.current.mentionables).toEqual([]);
  });

  it("loads the room directory and defaults to an empty page", async () => {
    mocks.getRoomDirectory.mockResolvedValueOnce({ items: [conversation], total: 7 });
    const ok = renderHook(() => useRoomDirectory(), { wrapper: makeWrapper() });
    await waitFor(() => expect(ok.result.current.total).toBe(7));
    expect(ok.result.current.rooms).toEqual([conversation]);
    expect(mocks.getRoomDirectory).toHaveBeenCalledWith(0, 50);

    mocks.getRoomDirectory.mockRejectedValueOnce(new Error("nope"));
    const bad = renderHook(() => useRoomDirectory(), { wrapper: makeWrapper() });
    await waitFor(() => expect(bad.result.current.error).toBeInstanceOf(Error));
    expect(bad.result.current.rooms).toEqual([]);
    expect(bad.result.current.total).toBe(0);
  });
});

describe("room participant writes", () => {
  const user = { kind: "user", id: "u1" } as const;

  it("runs add, remove and auto-reply updates for the room", async () => {
    mocks.addRoomParticipant.mockResolvedValue({ id: "added" });
    mocks.removeRoomParticipant.mockResolvedValue(undefined);
    mocks.updateRoomAgentAutoReply.mockResolvedValue({ id: "updated" });
    const wrapper = makeWrapper();
    const add = renderHook(() => useAddRoomParticipant("room-1"), { wrapper });
    const remove = renderHook(() => useRemoveRoomParticipant("room-1"), { wrapper });
    const update = renderHook(() => useUpdateRoomAgentAutoReply("room-1"), { wrapper });

    await act(async () => {
      expect(await add.result.current.add(user)).toEqual({ id: "added" });
      expect(await remove.result.current.remove(user)).toBeUndefined();
      expect(await update.result.current.update("a1", true)).toEqual({ id: "updated" });
    });

    expect(mocks.addRoomParticipant).toHaveBeenCalledWith("room-1", user);
    expect(mocks.removeRoomParticipant).toHaveBeenCalledWith("room-1", user);
    expect(mocks.updateRoomAgentAutoReply).toHaveBeenCalledWith("room-1", "a1", true);
    expect(add.result.current.isAdding).toBe(false);
    expect(remove.result.current.isRemoving).toBe(false);
    expect(update.result.current.isUpdating).toBe(false);
  });

  it("reports pending while a write is in flight", async () => {
    const response = deferred<unknown>();
    mocks.addRoomParticipant.mockReturnValueOnce(response.promise);
    const { result } = renderHook(() => useAddRoomParticipant("room-1"), {
      wrapper: makeWrapper(),
    });

    let pending!: Promise<unknown>;
    act(() => {
      pending = result.current.add(user);
    });
    expect(result.current.isAdding).toBe(true);
    await act(async () => {
      response.resolve({});
      await pending;
    });
    expect(result.current.isAdding).toBe(false);
  });

  it("does nothing without a room or scope", async () => {
    const none = renderHook(() => useAddRoomParticipant(null), { wrapper: makeWrapper() });
    expect(await none.result.current.add(user)).toBeNull();

    mocks.scope = { accountId: undefined as never, organizationId: "org-1", tenant: "org-1" };
    const noAccount = renderHook(() => useAddRoomParticipant("room-1"), {
      wrapper: makeWrapper(),
    });
    expect(await noAccount.result.current.add(user)).toBeNull();

    mocks.scope = { accountId: "user-1", organizationId: "org-1", tenant: null as never };
    const noTenant = renderHook(() => useAddRoomParticipant("room-1"), {
      wrapper: makeWrapper(),
    });
    expect(await noTenant.result.current.add(user)).toBeNull();
    expect(mocks.addRoomParticipant).not.toHaveBeenCalled();
  });

  it("does nothing once the scope has already changed", async () => {
    const { result } = renderHook(() => useAddRoomParticipant("room-1"), {
      wrapper: makeWrapper(),
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    expect(await result.current.add(user)).toBeNull();
    expect(mocks.addRoomParticipant).not.toHaveBeenCalled();
  });

  it("surfaces a failure, but drops one from a previous tenant", async () => {
    const wrapper = makeWrapper();
    mocks.addRoomParticipant.mockRejectedValueOnce(new Error("refused"));
    const { result } = renderHook(() => useAddRoomParticipant("room-1"), { wrapper });
    await act(async () => {
      await expect(result.current.add(user)).rejects.toThrow("refused");
    });

    const late = deferred<unknown>();
    mocks.addRoomParticipant.mockReturnValueOnce(late.promise);
    const stale = renderHook(() => useAddRoomParticipant("room-1"), { wrapper });
    let pending!: Promise<unknown>;
    act(() => {
      pending = stale.result.current.add(user);
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    await act(async () => {
      late.resolve({});
      expect(await pending).toBeNull();
    });

    mocks.scope = { accountId: "user-1", organizationId: "org-1", tenant: "org-1" };
    const lateFail = deferred<unknown>();
    mocks.addRoomParticipant.mockReturnValueOnce(lateFail.promise);
    const stale2 = renderHook(() => useAddRoomParticipant("room-1"), { wrapper });
    act(() => {
      pending = stale2.result.current.add(user);
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    await act(async () => {
      lateFail.reject(new Error("late"));
      expect(await pending).toBeNull();
    });
  });
});

describe("room create and join outcomes", () => {
  const input: CreateRoomConversationInput = {
    title: "Launch planning",
    visibility: "private",
    participants: [],
  };

  it("returns the created and joined room", async () => {
    mocks.createRoomConversation.mockResolvedValueOnce(conversation);
    mocks.joinPublicRoom.mockResolvedValueOnce(conversation);
    const wrapper = makeWrapper();
    const create = renderHook(() => useCreateRoomConversation(), { wrapper });
    const join = renderHook(() => useJoinPublicRoom(), { wrapper });

    await act(async () => {
      expect(await create.result.current.create(input)).toEqual(conversation);
      expect(await join.result.current.join("room-1")).toEqual(conversation);
    });
    expect(create.result.current.isCreating).toBe(false);
    expect(join.result.current.isJoining).toBe(false);
  });

  it("refuses without an account or tenant", async () => {
    mocks.scope = { accountId: undefined as never, organizationId: "org-1", tenant: "org-1" };
    const create = renderHook(() => useCreateRoomConversation(), { wrapper: makeWrapper() });
    const join = renderHook(() => useJoinPublicRoom(), { wrapper: makeWrapper() });
    expect(await create.result.current.create(input)).toBeNull();
    expect(await join.result.current.join("room-1")).toBeNull();
    expect(mocks.createRoomConversation).not.toHaveBeenCalled();
    expect(mocks.joinPublicRoom).not.toHaveBeenCalled();
  });

  it("surfaces a failure but swallows one from a previous tenant", async () => {
    const wrapper = makeWrapper();
    mocks.createRoomConversation.mockRejectedValueOnce(new Error("create refused"));
    mocks.joinPublicRoom.mockRejectedValueOnce(new Error("join refused"));
    const create = renderHook(() => useCreateRoomConversation(), { wrapper });
    const join = renderHook(() => useJoinPublicRoom(), { wrapper });
    await act(async () => {
      await expect(create.result.current.create(input)).rejects.toThrow("create refused");
      await expect(join.result.current.join("room-1")).rejects.toThrow("join refused");
    });

    const createLate = deferred<Conversation>();
    const joinLate = deferred<Conversation>();
    mocks.createRoomConversation.mockReturnValueOnce(createLate.promise);
    mocks.joinPublicRoom.mockReturnValueOnce(joinLate.promise);
    const create2 = renderHook(() => useCreateRoomConversation(), { wrapper });
    const join2 = renderHook(() => useJoinPublicRoom(), { wrapper });
    let pendingCreate!: Promise<Conversation | null>;
    let pendingJoin!: Promise<Conversation | null>;
    act(() => {
      pendingCreate = create2.result.current.create(input);
      pendingJoin = join2.result.current.join("room-1");
    });
    mocks.scope = { accountId: "user-1", organizationId: "org-2", tenant: "org-2" };
    await act(async () => {
      createLate.reject(new Error("late"));
      joinLate.reject(new Error("late"));
      expect(await pendingCreate).toBeNull();
      expect(await pendingJoin).toBeNull();
    });
  });
});
