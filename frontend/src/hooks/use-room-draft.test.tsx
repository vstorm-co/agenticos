import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FileUploadResponse } from "@/lib/file-api";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { RoomParticipantRead } from "@/types/room";
import { useRoomDraft } from "./use-room-draft";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const key = JSON.stringify(["me", "org-a", "room-a", null]);
const threadKey = JSON.stringify(["me", "org-a", "room-a", "root-1"]);

function file(id: string): FileUploadResponse {
  return {
    id,
    filename: `${id}.txt`,
    mime_type: "text/plain",
    size: 3,
    file_type: "text",
    preview: null,
  };
}

const upload = (id: string) => ({ id, name: `${id}.txt`, size: 3 });

const alex: RoomParticipantRead = {
  kind: "user",
  id: "user-2",
  name: "Alex",
  avatar_url: null,
  is_member: true,
  can_add: false,
  can_mention: true,
  auto_reply: false,
};

const held = () => useChatStore.getState().roomDrafts[key];

beforeEach(() => {
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
  useChatStore.setState({ messages: [], replyTo: null, roomDrafts: {}, roomDraftGeneration: 0 });
});
afterEach(() => client.clear());

describe("room draft upload tracking", () => {
  it("accepts one batch of uploads at a time and ignores empty batches", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });

    let began = true;
    act(() => {
      began = result.current.beginUploads([]);
    });
    expect(began).toBe(false);
    act(() => {
      began = result.current.beginUploads([upload("u1")]);
    });
    expect(began).toBe(true);
    expect(result.current.pendingUploads).toEqual([upload("u1")]);
    act(() => {
      began = result.current.beginUploads([upload("u2")]);
    });
    expect(began).toBe(false);
    expect(result.current.pendingUploads).toEqual([upload("u1")]);
  });

  it("refuses a new batch while an attempt is held", () => {
    useChatStore.getState().updateRoomDraft(key, (value) => ({
      ...value,
      attempt: { input: { client_message_id: "c", content: "x", mentions: [] }, reply: null },
    }));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    let began = true;
    act(() => {
      began = result.current.beginUploads([upload("u1")]);
    });
    expect(began).toBe(false);
  });

  it("attaches a completed upload once and ignores unknown or duplicate ones", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.beginUploads([upload("u1"), upload("u2")]);
    });

    let done = true;
    act(() => {
      done = result.current.completeUpload("missing", file("f0"));
    });
    expect(done).toBe(false);
    act(() => {
      done = result.current.completeUpload("u1", file("f1"));
    });
    expect(done).toBe(true);
    act(() => {
      done = result.current.completeUpload("u2", file("f1"));
    });
    expect(done).toBe(true);
    expect(result.current.attachments.map((item) => item.id)).toEqual(["f1"]);
    expect(result.current.pendingUploads).toEqual([]);
  });

  it("does not attach a completed upload while an attempt is held", () => {
    useChatStore.getState().updateRoomDraft(key, (value) => ({
      ...value,
      pendingUploads: [upload("u1")],
      attempt: { input: { client_message_id: "c", content: "x", mentions: [] }, reply: null },
    }));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.completeUpload("u1", file("f1"));
    });
    expect(held()?.attachments).toEqual([]);
    expect(held()?.pendingUploads).toEqual([]);
  });

  it("records an upload failure, then clears it", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.beginUploads([upload("u1")]);
    });

    let failed = true;
    act(() => {
      failed = result.current.failUpload("missing", "boom");
    });
    expect(failed).toBe(false);
    act(() => {
      failed = result.current.failUpload("u1", "boom");
    });
    expect(failed).toBe(true);
    expect(result.current.uploadError).toBe("boom");
    expect(result.current.pendingUploads).toEqual([]);

    act(() => {
      result.current.clearUploadError();
    });
    expect(result.current.uploadError).toBeNull();
    act(() => {
      result.current.clearUploadError();
    });
    expect(result.current.uploadError).toBeNull();
  });
});

describe("room draft attachments, content and intent", () => {
  it("adds an attachment once and removes it by id", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.addAttachment(file("f1"));
      result.current.addAttachment(file("f1"));
      result.current.addAttachment(file("f2"));
    });
    expect(result.current.attachments.map((item) => item.id)).toEqual(["f1", "f2"]);

    act(() => {
      result.current.removeAttachment("f1");
    });
    expect(result.current.attachments.map((item) => item.id)).toEqual(["f2"]);
  });

  it("keeps attachments frozen while an attempt is held", () => {
    useChatStore.getState().updateRoomDraft(key, (value) => ({
      ...value,
      attachments: [file("f1")],
      attempt: { input: { client_message_id: "c", content: "x", mentions: [] }, reply: null },
    }));
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.addAttachment(file("f2"));
      result.current.removeAttachment("f1");
    });
    expect(result.current.attachments.map((item) => item.id)).toEqual(["f1"]);
    expect(result.current.locked).toBe(true);
  });

  it("tracks content with an edit hint, picks a mention and switches intent", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.setContent("Hi @Al", { caret: 6, selectionEnd: 6 });
    });
    let caret = 0;
    act(() => {
      caret = result.current.pickMention({ start: 3, query: "Al" }, alex);
    });
    expect(caret).toBe(9);
    expect(result.current.content).toBe("Hi @Alex ");
    expect(result.current.roomMentions).toEqual([
      { kind: "user", id: "user-2", name: "Alex", start: 3, end: 8 },
    ]);

    act(() => {
      result.current.setAskLead();
    });
    expect(result.current.intent).toBe("ask_lead");
    act(() => {
      result.current.setMessageIntent();
    });
    expect(result.current.intent).toBe("message");
  });

  it("reports whether uploads may continue in the same scope", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    const before = result.current;
    expect(before.canContinueUpload()).toBe(true);
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    expect(before.canContinueUpload()).toBe(false);
  });

  it("ignores writes from a draft handle that predates a draft reset", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    const stale = result.current;
    act(() => useChatStore.getState().clearRoomDrafts());

    let changed = true;
    act(() => {
      changed = stale.setContent("late");
    });
    expect(changed).toBe(false);
    expect(held()).toBeUndefined();
  });
});

describe("room draft replies", () => {
  const parent = { messageId: "parent", role: "user" as const, excerpt: "Earlier" };

  it("keeps a main-room reply in the chat store", () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => result.current.setReply(parent));
    expect(useChatStore.getState().replyTo).toEqual(parent);
    expect(result.current.reply).toEqual(parent);
    act(() => result.current.clearReply());
    expect(useChatStore.getState().replyTo).toBeNull();
  });

  it("keeps a thread reply in the thread draft", () => {
    const { result } = renderHook(() => useRoomDraft("room-a", "root-1"), { wrapper });
    act(() => result.current.setReply(parent));
    expect(useChatStore.getState().roomDrafts[threadKey]?.reply).toEqual(parent);
    expect(result.current.reply).toEqual(parent);
    expect(useChatStore.getState().replyTo).toBeNull();
    act(() => result.current.clearReply());
    expect(result.current.reply).toBeNull();
  });
});
