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

  it.each([
    ["task id", { task_id: null }],
    ["task conversation id", { task_conversation_id: null }],
  ] as const)("does not navigate to the source chat when the %s is missing", async (_, missing) => {
    runAsTask.mockRejectedValueOnce(new Error("network"));
    get.mockResolvedValueOnce(taskReceipt(missing));

    const outcome = await transferAcceptedQueueItem("source-chat", "receipt-1");

    expect(outcome.kind).toBe("unknown");
  });

  it("uses a complete task response without an extra receipt read", async () => {
    runAsTask.mockResolvedValueOnce({
      id: "task-2",
      conversation_id: "task-topic-2",
      status: "queued",
    });

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toEqual({
      kind: "task",
      task: { id: "task-2", conversation_id: "task-topic-2", status: "queued" },
    });
    expect(get).not.toHaveBeenCalled();
  });

  it("recovers task metadata when the action response is incomplete", async () => {
    runAsTask.mockResolvedValueOnce({ id: "task-1", conversation_id: "" });
    get.mockResolvedValueOnce(taskReceipt());

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "task",
      task: { conversation_id: "task-topic-1" },
    });
  });

  it.each(["sent", "steered", "cancelled"] as const)(
    "uses the receipt's %s disposition after a lost task response",
    async (state) => {
      runAsTask.mockRejectedValueOnce(new Error("network"));
      get.mockResolvedValueOnce(taskReceipt({ state }));

      await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toEqual({
        kind: state,
      });
    },
  );

  it("returns pending receipt state when an incomplete task response did not transfer it", async () => {
    runAsTask.mockResolvedValueOnce({ id: "task-1", conversation_id: "" });
    get.mockResolvedValueOnce(taskReceipt({ state: "pending" }));

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "pending",
      error: expect.any(Error),
    });
  });

  it("keeps the outcome unknown when both an incomplete response and receipt read fail", async () => {
    runAsTask.mockResolvedValueOnce({ id: "", conversation_id: "" });
    get.mockRejectedValueOnce(new Error("offline"));

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "unknown",
      error: expect.any(Error),
    });
  });

  it("keeps the original task error when receipt recovery also fails", async () => {
    const networkError = new Error("network");
    runAsTask.mockRejectedValueOnce(networkError);
    get.mockRejectedValueOnce(new Error("offline"));

    await expect(transferAcceptedQueueItem("source-chat", "receipt-1")).resolves.toEqual({
      kind: "unknown",
      error: networkError,
    });
  });

  it("keeps cancellation unresolved when neither response nor receipt can be read", async () => {
    cancel.mockRejectedValueOnce(new Error("network"));
    get.mockRejectedValueOnce(new Error("offline"));

    await expect(cancelAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "unknown",
    });
  });

  it("reconciles a successful cancellation response that is still pending", async () => {
    cancel.mockResolvedValueOnce(taskReceipt({ state: "steering" }));

    await expect(cancelAcceptedQueueItem("source-chat", "receipt-1")).resolves.toMatchObject({
      kind: "steering",
      error: expect.any(Error),
    });
    expect(get).not.toHaveBeenCalled();
  });

  it("uses a terminal receipt after a lost cancellation response", async () => {
    cancel.mockRejectedValueOnce(new Error("network"));
    get.mockResolvedValueOnce(taskReceipt({ state: "cancelled" }));

    await expect(cancelAcceptedQueueItem("source-chat", "receipt-1")).resolves.toEqual({
      kind: "cancelled",
    });
  });
});
