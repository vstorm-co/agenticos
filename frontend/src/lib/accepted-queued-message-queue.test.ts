import { describe, expect, it } from "vitest";

import type { QueuedMessage } from "@/types/chat";
import type { AcceptedQueuedMessageReceipt } from "./accepted-queued-messages-api";
import {
  acceptedQueuePayload,
  ensureQueueClientId,
  queueFromReceipt,
  queueMayDrain,
  queueMaySteer,
  queueReceiptPayloadUnsupportedReason,
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

  it("keeps existing idempotency keys and explains unsupported frozen payloads", () => {
    const valid = queued();
    expect(ensureQueueClientId(valid)).toBe(valid);

    const alreadyAccepted = queued({ acceptedQueueId: receiptId, clientQueueId: undefined });
    expect(ensureQueueClientId(alreadyAccepted)).toBe(alreadyAccepted);

    const legacy = queued({ clientQueueId: "legacy-id", acceptedQueueId: undefined });
    expect(ensureQueueClientId(legacy).clientQueueId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );

    expect(queueReceiptPayloadUnsupportedReason(queued({ agentId: null }))).toBe("agent");
    expect(queueReceiptPayloadUnsupportedReason(queued({ clientQueueId: undefined }))).toBe(
      "client_id",
    );
    expect(acceptedQueuePayload(queued({ clientQueueId: "bad-id" }))).toBeNull();
    expect(
      queueReceiptPayloadUnsupportedReason(
        queued({ queueSettings: { modelProfileId: null, approvalMode: "ask_all" } }),
      ),
    ).toBe("settings");
    expect(
      queueReceiptPayloadUnsupportedReason(
        queued({
          submission: {
            agentId: "agent-1",
            pageContext: null,
            local: { payload: { folder: "C:/other" }, fileRoot: "C:/work", projectId: null },
          },
        }),
      ),
    ).toBe("context");

    const fromSubmission = queued({
      agentId: undefined,
      submission: { agentId: "agent-2", pageContext: null },
    });
    expect(acceptedQueuePayload(fromSubmission)?.agent_id).toBe("agent-2");
    expect(acceptedQueuePayload(queued({ agentId: undefined }))).toBeNull();
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

  it("keeps refused, in-flight, and unconfirmed rows out of the drain", () => {
    const blocked: Array<QueuedMessage | undefined> = [
      undefined,
      queued({ refused: "server refused it" }),
      queued({ accepting: true }),
      queued({ transferring: true }),
      queued({ cancelRequested: true }),
      queued({ receiptError: "unknown receipt" }),
      queued({ transferError: "unknown transfer" }),
    ];
    for (const message of blocked) expect(queueMayDrain(message, true)).toBe(false);
    expect(queueMayDrain(queued({ acceptedQueueId: receiptId }), false)).toBe(false);
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

  it("preserves matching local files and mention labels while rebuilding receipt context", () => {
    const mention = { kind: "collection" as const, id: "collection-1", name: "Reports" };
    const file = {
      id: "file-1",
      filename: "report.txt",
      mime_type: "text/plain",
      file_type: "text",
    };
    const existing = queued({
      fileIds: ["file-1"],
      files: [file],
      mentions: [mention],
      replyTo: { messageId: "reply-1", role: "assistant", excerpt: "old" },
    });
    const restored = queueFromReceipt(
      receipt({
        file_ids: ["file-1"],
        mentions: [{ kind: "collection", id: "collection-1" }],
        local_target: { folder: "C:/work", project_id: "project-1" },
        reply_to_message_id: "reply-1",
        reply_to_role: "assistant",
        quote_excerpt: "saved excerpt",
      }),
      existing,
    );

    expect(restored.files).toBe(existing.files);
    expect(restored.mentions).toEqual([mention]);
    expect(restored.submission?.local).toMatchObject({
      fileRoot: "C:/work",
      projectId: "project-1",
    });
    expect(restored.replyTo).toMatchObject({ messageId: "reply-1", excerpt: "saved excerpt" });

    const rebuilt = queueFromReceipt(
      receipt({
        mentions: [{ kind: "agent", id: "agent-2" }],
        local_target: { folder: 42, project_id: 17, computer_grant: "grant-1" },
        reply_to_message_id: null,
        reply_to_role: null,
      }),
      existing,
    );
    expect(rebuilt.files).toBeUndefined();
    expect(rebuilt.mentions).toEqual([{ kind: "agent", id: "agent-2", name: "agent-2" }]);
    expect(rebuilt.submission?.local).toMatchObject({ fileRoot: null, projectId: null });
    expect(rebuilt.replyTo).toBeUndefined();

    const grantedComputer = queueFromReceipt(
      receipt({ local_target: { folder: "C:/work", computer_grant: "computer-1" } }),
    );
    expect(grantedComputer.submission?.local).toMatchObject({ fileRoot: null });
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

  it("allows task transfer when local access has a device and no extra grant", () => {
    expect(queueTaskUnavailableReason(queued())).toBeNull();
    expect(
      queueTaskUnavailableReason(
        queued({
          submission: {
            agentId: "agent-1",
            pageContext: null,
            local: {
              payload: { device_id: "device-1", routine_grant: "routine-1" },
              fileRoot: null,
              projectId: null,
            },
          },
        }),
      ),
    ).toBe("routine_grant");
    expect(
      queueTaskUnavailableReason(
        queued({
          submission: {
            agentId: "agent-1",
            pageContext: null,
            local: { payload: { device_id: "device-1" }, fileRoot: null, projectId: null },
          },
        }),
      ),
    ).toBeNull();
  });
});
