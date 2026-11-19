import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/types/conversation";
import { useCreateRoomConversation, useJoinPublicRoom } from "./use-room-participants";

const mocks = vi.hoisted(() => ({
  scope: { accountId: "user-1", organizationId: "org-1", tenant: "org-1" },
  createRoomConversation: vi.fn(),
  joinPublicRoom: vi.fn(),
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
  addRoomParticipant: vi.fn(),
  createRoomConversation: mocks.createRoomConversation,
  getRoomDirectory: vi.fn(),
  getRoomMentionables: vi.fn(),
  getRoomParticipants: vi.fn(),
  joinPublicRoom: mocks.joinPublicRoom,
  removeRoomParticipant: vi.fn(),
  updateRoomAgentAutoReply: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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
