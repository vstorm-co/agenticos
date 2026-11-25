import { beforeEach, describe, expect, it, vi } from "vitest";

const { cancel, get, runAsTask } = vi.hoisted(() => ({
  cancel: vi.fn(),
  get: vi.fn(),
  runAsTask: vi.fn(),
}));

vi.mock("./accepted-queued-messages-api", () => ({
  acceptedQueuedMessagesApi: { cancel, get, runAsTask },
}));

import {
  cancelAcceptedQueueItem,
  transferAcceptedQueueItem,
} from "./accepted-queued-message-transfer";

function taskReceipt(overrides: Record<string, unknown> = {}) {
  return {
    id: "receipt-1",
    client_queue_id: "client-1",
    conversation_id: "source-chat",
    agent_id: "agent-1",
    content: "Run this as a task",
    file_ids: [],
    mentions: [],
    reply_to_message_id: null,
    reply_to_excerpt: null,
    page_context: null,
    local_target: null,
    state: "task",
    message_id: null,
    task_id: "task-1",
    task_conversation_id: "task-topic-1",
    steering_run_id: null,
    reply_to_role: null,
    quote_excerpt: null,
    created_at: "2026-11-25T00:00:00Z",
    ...overrides,
  };
}

describe("accepted queue transfer reconciliation", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the returned task topic after a lost response", async () => {
    runAsTask.mockRejectedValueOnce(new Error("network"));
    get.mockResolvedValueOnce(taskReceipt());

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toEqual({
      kind: "task",
      task: { id: "task-1", conversation_id: "task-topic-1", status: "queued" },
    });
    expect(get).toHaveBeenCalledWith("source-chat", "receipt-1");
  });

  it("does not navigate to the source chat when task topic metadata is incomplete", async () => {
    runAsTask.mockRejectedValueOnce(new Error("network"));
    get.mockResolvedValueOnce(taskReceipt({ task_conversation_id: null }));

    const outcome = await transferAcceptedQueueItem("source-chat", "receipt-1");

    expect(outcome.kind).toBe("unknown");
  });

  it("recovers task metadata when the action response is incomplete", async () => {
    runAsTask.mockResolvedValueOnce({ id: "task-1", conversation_id: "" });
    get.mockResolvedValueOnce(taskReceipt());

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "task",
      task: { conversation_id: "task-topic-1" },
    });
  });

  it("keeps cancellation unresolved when neither response nor receipt can be read", async () => {
    cancel.mockRejectedValueOnce(new Error("network"));
    get.mockRejectedValueOnce(new Error("offline"));

    await expect(cancelAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "unknown",
    });
  });
});
