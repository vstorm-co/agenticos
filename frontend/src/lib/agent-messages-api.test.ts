import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import {
  agentMessageAttachmentUrl,
  getAgentMessageThread,
  listAgentMessageRecipients,
  listAgentMessages,
  listAgentMessageThreads,
  markAgentMessageThreadRead,
  reactToAgentMessage,
  sendAgentMessage,
} from "./agent-messages-api";
import type {
  AgentMessageRead,
  AgentMessageSend,
  AgentMessageThreadRead,
} from "@/types/agent-messages";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

const thread: AgentMessageThreadRead = {
  id: "thread-1",
  agent_a: { id: "agent-a", slug: "planner", name: "Planner" },
  agent_b: { id: "agent-b", slug: "reviewer", name: "Reviewer" },
  last_message_at: null,
  last_message: null,
  unread: true,
  created_at: "2026-11-14T08:00:00Z",
  updated_at: "2026-11-14T08:00:00Z",
};

const message: AgentMessageRead = {
  id: "message-1",
  thread_id: thread.id,
  sender_agent_id: "agent-a",
  sender_agent_slug: "planner",
  sender_user_id: "person-1",
  body: "Please review this plan.",
  reply_to_message_id: "message-0",
  reactions: [],
  attachments: [],
  created_at: thread.created_at,
  updated_at: thread.updated_at,
};

beforeEach(() => {
  vi.resetAllMocks();
});

describe("agent-message API transport", () => {
  it.each([
    {
      name: "thread defaults",
      read: () => listAgentMessageThreads(),
      path: "/agent-messages",
      params: { skip: "0", limit: "50" },
    },
    {
      name: "a later thread page",
      read: () => listAgentMessageThreads(50, 25),
      path: "/agent-messages",
      params: { skip: "50", limit: "25" },
    },
    {
      name: "recipient defaults",
      read: () => listAgentMessageRecipients(),
      path: "/agent-messages/recipients",
      params: { skip: "0", limit: "100" },
    },
    {
      name: "a later recipient page",
      read: () => listAgentMessageRecipients(100, 20),
      path: "/agent-messages/recipients",
      params: { skip: "100", limit: "20" },
    },
    {
      name: "message defaults",
      read: () => listAgentMessages(thread.id),
      path: "/agent-messages/thread-1/messages",
      params: { skip: "0", limit: "50" },
    },
    {
      name: "a later message page",
      read: () => listAgentMessages(thread.id, 50, 10),
      path: "/agent-messages/thread-1/messages",
      params: { skip: "50", limit: "10" },
    },
  ])("reads $name with the backend pagination contract", async ({ read, path, params }) => {
    const page = { items: [], total: 123 };
    vi.mocked(apiClient.get).mockResolvedValueOnce(page);

    await expect(read()).resolves.toBe(page);

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith(path, { params });
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("reads one thread without introducing paging or changing its permission-scoped agents", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(thread);

    await expect(getAgentMessageThread(thread.id)).resolves.toBe(thread);

    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith("/agent-messages/thread-1");
  });

  it("sends the selected sender, recipient, reply and attachment IDs unchanged", async () => {
    const input: AgentMessageSend = {
      sender_agent_id: "agent-a",
      recipient: "reviewer",
      body: message.body,
      reply_to_message_id: "message-0",
      attachment_file_ids: ["file-1", "file-2"],
    };
    vi.mocked(apiClient.post).mockResolvedValueOnce(message);

    await expect(sendAgentMessage(input)).resolves.toBe(message);

    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/agent-messages", input);
  });

  it.each([undefined, null, "agent-a"])(
    "preserves the reaction identity when asAgentId is %s",
    async (asAgentId) => {
      const response = { reacted: true, reactions: [] };
      vi.mocked(apiClient.post).mockResolvedValueOnce(response);

      await expect(reactToAgentMessage(thread.id, message.id, "👍", asAgentId)).resolves.toBe(
        response,
      );

      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
        "/agent-messages/thread-1/messages/message-1/reactions",
        { emoji: "👍", as_agent_id: asAgentId ?? null },
      );
    },
  );

  it("accepts the empty 204 body when marking a thread read", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(undefined);

    await expect(markAgentMessageThreadRead(thread.id)).resolves.toBeUndefined();

    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/agent-messages/thread-1/read",
      undefined,
    );
  });

  it.each([
    { name: "threads", request: () => listAgentMessageThreads() },
    { name: "recipients", request: () => listAgentMessageRecipients() },
    { name: "thread", request: () => getAgentMessageThread(thread.id) },
    { name: "messages", request: () => listAgentMessages(thread.id) },
    {
      name: "send",
      request: () =>
        sendAgentMessage({ sender_agent_id: "agent-a", recipient: "reviewer", body: "Review" }),
    },
    {
      name: "reaction",
      request: () => reactToAgentMessage(thread.id, message.id, "👍", "agent-a"),
    },
    { name: "read watermark", request: () => markAgentMessageThreadRead(thread.id) },
  ])("does not hide an authorization refusal from $name", async ({ request }) => {
    const refusal = new ApiError(403, "You may not run this agent.");
    vi.mocked(apiClient.get).mockRejectedValueOnce(refusal);
    vi.mocked(apiClient.post).mockRejectedValueOnce(refusal);

    await expect(request()).rejects.toBe(refusal);
  });

  it("links an attachment through the authenticated BFF without reading its bytes into JavaScript", () => {
    expect(agentMessageAttachmentUrl(thread.id, message.id, "file-1")).toBe(
      "/api/agent-messages/thread-1/messages/message-1/attachments/file-1?disposition=inline",
    );
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
