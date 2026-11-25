import { describe, expect, it } from "vitest";

import type { QueuedMessage } from "@/types/chat";
import type { AcceptedQueuedMessageReceipt } from "./accepted-queued-messages-api";
import {
  acceptedQueuePayload,
  queueFromReceipt,
  queueMayDrain,
  queueMaySteer,
  queueTaskUnavailableReason,
} from "./accepted-queued-message-queue";

const clientId = "123e4567-e89b-42d3-a456-426614174000";
const receiptId = "123e4567-e89b-42d3-a456-426614174001";

function queued(overrides: Partial<QueuedMessage> = {}): QueuedMessage {
  return {
    id: "row-1",
    clientQueueId: clientId,
    acceptedQueueId: receiptId,
    receiptConversationId: "conversation-1",
    receiptState: "pending",
    agentId: "agent-1",
    content: "Check the figures",
    queueSettings: { modelProfileId: null, approvalMode: "follow_agent" },
    ...overrides,
  };
}

function receipt(
  overrides: Partial<AcceptedQueuedMessageReceipt> = {},
): AcceptedQueuedMessageReceipt {
  return {
    id: receiptId,
    client_queue_id: clientId,
    conversation_id: "conversation-1",
    agent_id: "agent-1",
    content: "Check the figures",
    file_ids: [],
    mentions: [],
    reply_to_message_id: null,
    reply_to_excerpt: null,
    page_context: null,
    local_target: null,
    state: "pending",
    message_id: null,
    task_id: null,
    task_conversation_id: null,
    steering_run_id: null,
    reply_to_role: null,
    quote_excerpt: null,
    created_at: "2026-11-25T00:00:00Z",
    ...overrides,
  };
}

describe("accepted queued message payloads", () => {
  it("keeps the full user payload and refuses settings or local fields receipts cannot represent", () => {
    const message = queued({
      fileIds: ["file-1"],
      mentions: [{ kind: "collection", id: "collection-1", name: "Reports" }],
      replyTo: {
        messageId: "message-1",
        role: "assistant",
        excerpt: "prior answer",
        selectedText: "selected quote",
      },
      submission: {
        agentId: "agent-1",
        pageContext: {
          path: "/reports",
          title: "Reports",
          captured_at: "2026-11-25T00:00:00Z",
        },
        local: {
          payload: { folder: "C:/work", device_id: "device-1" },
          fileRoot: "C:/work",
          projectId: null,
        },
      },
    });

    expect(acceptedQueuePayload(message)).toEqual({
      client_queue_id: clientId,
      agent_id: "agent-1",
      content: "Check the figures",
      file_ids: ["file-1"],
      mentions: [{ kind: "collection", id: "collection-1" }],
      reply_to_message_id: "message-1",
      reply_to_excerpt: "selected quote",
      page_context: message.submission?.pageContext,
      local_target: { folder: "C:/work", device_id: "device-1" },
    });
    expect(
      acceptedQueuePayload(
        queued({
          submission: {
            agentId: "agent-1",
            pageContext: null,
            local: { payload: null, fileRoot: null, projectId: "project-1" },
          },
        }),
      ),
    ).toBeNull();
    expect(
      acceptedQueuePayload(
        queued({ queueSettings: { modelProfileId: "custom-model", approvalMode: "follow_agent" } }),
      ),
    ).toBeNull();
    expect(acceptedQueuePayload(queued({ queueSettings: undefined }))).toBeNull();
  });

  it("does not let receipt mode drain rows without a valid pending receipt", () => {
    expect(queueMayDrain(queued(), true)).toBe(true);
    expect(queueMayDrain(queued({ agentId: undefined }), true)).toBe(false);
    expect(queueMayDrain(queued({ clientQueueId: "bad-id" }), true)).toBe(false);
    expect(queueMayDrain(queued({ acceptedQueueId: undefined }), true)).toBe(false);
    expect(queueMayDrain(queued({ receiptUnsupported: true }), true)).toBe(false);
    expect(queueMayDrain(queued({ receiptState: "steering" }), true)).toBe(false);
    expect(queueMayDrain(queued(), false)).toBe(false);
    expect(queueMayDrain({ id: "legacy", content: "legacy row" }, false)).toBe(true);
  });

  it("steers only plain text for the live frozen agent", () => {
    expect(queueMaySteer(queued(), "agent-1", true)).toBe(true);
    expect(queueMaySteer(queued(), "agent-2", true)).toBe(false);
    expect(queueMaySteer(queued({ fileIds: ["file-1"] }), "agent-1", true)).toBe(false);
    expect(
      queueMaySteer(
        queued({
          submission: {
            agentId: "agent-1",
            pageContext: null,
            local: { payload: { device_id: "device-1" }, fileRoot: null, projectId: null },
          },
        }),
        "agent-1",
        true,
      ),
    ).toBe(false);
    expect(queueMaySteer(queued({ receiptState: "steering" }), "agent-1", true)).toBe(false);
    expect(
      queueMaySteer(
        queued({ transferError: "Task status is unknown", transferErrorAction: "task" }),
        "agent-1",
        true,
      ),
    ).toBe(false);
  });

  it("rebuilds receipt truth without retaining stale files or quoted text", () => {
    const existing = queued({
      files: [{ id: "old-file", filename: "old.txt", mime_type: "text/plain", file_type: "text" }],
      fileIds: ["old-file"],
      replyTo: {
        messageId: "reply-1",
        role: "assistant",
        excerpt: "old quote",
        selectedText: "stale selected text",
      },
    });
    const restored = queueFromReceipt(
      receipt({
        file_ids: ["new-file"],
        reply_to_message_id: "reply-1",
        reply_to_role: "assistant",
        quote_excerpt: "saved quote",
        reply_to_excerpt: null,
      }),
      existing,
    );

    expect(restored.fileIds).toEqual(["new-file"]);
    expect(restored.files).toBeUndefined();
    expect(restored.replyTo).toMatchObject({ excerpt: "saved quote", selectedText: undefined });
  });

  it("blocks task transfer for unsupported local targets while preserving pending drain", () => {
    const computer = queued({
      submission: {
        agentId: "agent-1",
        pageContext: null,
        local: { payload: { computer_grant: "grant-1" }, fileRoot: null, projectId: null },
      },
    });
    const noDevice = queued({
      submission: {
        agentId: "agent-1",
        pageContext: null,
        local: { payload: { browser: true }, fileRoot: null, projectId: null },
      },
    });
    expect(queueTaskUnavailableReason(computer)).toBe("computer_grant");
    expect(queueTaskUnavailableReason(noDevice)).toBe("device_id");
    expect(queueMayDrain(computer, true)).toBe(true);
  });
});
