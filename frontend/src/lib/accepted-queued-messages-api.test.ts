import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post, del } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({ apiClient: { get, post, delete: del } }));

import {
  acceptedQueuedMessagesApi,
  listAcceptedQueuedMessages,
  newQueueClientId,
} from "./accepted-queued-messages-api";

describe("accepted queued message API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the personal conversation receipt endpoints", async () => {
    const receipt = { id: "receipt-1" };
    post.mockResolvedValueOnce(receipt).mockResolvedValueOnce({ id: "task-1" });
    get.mockResolvedValueOnce(receipt);
    del.mockResolvedValueOnce(receipt);

    await acceptedQueuedMessagesApi.accept("chat/1", {
      client_queue_id: "client-1",
      agent_id: "agent-1",
      content: "hello",
      file_ids: [],
      mentions: [],
      reply_to_message_id: null,
      reply_to_excerpt: null,
      page_context: null,
      local_target: null,
    });
    await acceptedQueuedMessagesApi.get("chat/1", "receipt/1");
    await acceptedQueuedMessagesApi.cancel("chat/1", "receipt/1");
    await acceptedQueuedMessagesApi.runAsTask("chat/1", "receipt/1");

    expect(post.mock.calls.map(([url]) => url)).toEqual([
      "/conversations/chat%2F1/queued-messages",
      "/conversations/chat%2F1/queued-messages/receipt%2F1/run-as-task",
    ]);
    expect(get).toHaveBeenCalledWith("/conversations/chat%2F1/queued-messages/receipt%2F1");
    expect(del).toHaveBeenCalledWith("/conversations/chat%2F1/queued-messages/receipt%2F1");
  });

  it("loads every unresolved page before recovery is considered complete", async () => {
    get
      .mockResolvedValueOnce({ items: [{ id: "receipt-1" }], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [{ id: "receipt-2" }], next_cursor: null });

    const items = await listAcceptedQueuedMessages("chat-1");

    expect(items.map((item) => item.id)).toEqual(["receipt-1", "receipt-2"]);
    expect(get).toHaveBeenNthCalledWith(1, "/conversations/chat-1/queued-messages", {
      signal: undefined,
    });
    expect(get).toHaveBeenNthCalledWith(2, "/conversations/chat-1/queued-messages", {
      signal: undefined,
      params: { cursor: "page-2" },
    });
  });

  it("fails closed when a broken cursor repeats instead of returning a partial list", async () => {
    get.mockResolvedValue({ items: [], next_cursor: "same-page" });

    await expect(listAcceptedQueuedMessages("chat-1")).rejects.toThrow();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("creates a valid version-four id when the platform has no randomUUID", () => {
    vi.stubGlobal("crypto", undefined);

    try {
      expect(newQueueClientId()).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
