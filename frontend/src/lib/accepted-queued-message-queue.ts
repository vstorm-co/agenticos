import type { QueuedMessage } from "@/types/chat";
import type { Mentionable } from "@/types/mention";
import {
  newQueueClientId,
  type AcceptedQueuedMessagePayload,
  type AcceptedQueuedMessageReceipt,
} from "@/lib/accepted-queued-messages-api";

export { newQueueClientId } from "@/lib/accepted-queued-messages-api";

/** Give a pre-receipt device-outbox row a stable idempotency key before posting it. */
export function ensureQueueClientId(message: QueuedMessage): QueuedMessage {
  if (message.acceptedQueueId || isUuid(message.clientQueueId ?? "")) return message;
  return { ...message, clientQueueId: newQueueClientId() };
}

/** The receipt freezes every supported user-authored part of the queue payload. */
export function acceptedQueuePayload(message: QueuedMessage): AcceptedQueuedMessagePayload | null {
  const clientQueueId = message.clientQueueId;
  const agentId = message.agentId ?? message.submission?.agentId;
  if (!agentId || !clientQueueId || !isUuid(clientQueueId)) return null;
  if (queueReceiptPayloadUnsupportedReason(message) !== null) return null;

  const local = message.submission?.local;
  const localTarget = local?.payload ?? null;
  return {
    client_queue_id: clientQueueId,
    agent_id: agentId,
    content: message.content,
    file_ids: message.fileIds ?? [],
    mentions: (message.mentions ?? []).map(({ kind, id }) => ({ kind, id })),
    reply_to_message_id: message.replyTo?.messageId ?? null,
    reply_to_excerpt: message.replyTo?.selectedText ?? null,
    page_context: message.submission?.pageContext ?? null,
    local_target: localTarget,
  };
}

export function queueReceiptPayloadUnsupportedReason(
  message: QueuedMessage,
): "agent" | "client_id" | "context" | "settings" | "snapshot" | null {
  const agentId = message.agentId ?? message.submission?.agentId;
  if (!agentId) return "agent";
  if (!message.clientQueueId || !isUuid(message.clientQueueId)) return "client_id";
  if (!message.queueSettings) return "snapshot";
  if (
    message.queueSettings.modelProfileId !== null ||
    message.queueSettings.approvalMode !== "follow_agent"
  ) {
    return "settings";
  }
  const local = message.submission?.local;
  if (local?.projectId) return "context";
  if (local?.fileRoot && local.payload?.folder !== local.fileRoot) return "context";
  return null;
}

/** Rebuild a lost browser outbox row from its authenticated server receipt. */
export function queueFromReceipt(
  receipt: AcceptedQueuedMessageReceipt,
  existing?: QueuedMessage,
): QueuedMessage {
  const fileIds = receipt.file_ids;
  const sameMentions =
    existing?.mentions?.length === receipt.mentions.length &&
    receipt.mentions.every((ref) =>
      existing.mentions?.some((mention) => mention.kind === ref.kind && mention.id === ref.id),
    );
  const mentions: Mentionable[] = sameMentions
    ? (existing?.mentions ?? [])
    : receipt.mentions.map((ref) => ({ ...ref, name: ref.id }));
  const filesMatch =
    existing?.fileIds?.length === fileIds.length &&
    fileIds.every((fileId) => existing?.fileIds?.includes(fileId));
  const localTarget = receipt.local_target;
  const localFolder = typeof localTarget?.folder === "string" ? localTarget.folder : null;
  const localProjectId =
    typeof localTarget?.project_id === "string" ? localTarget.project_id : null;
  const replyTo =
    receipt.reply_to_message_id && receipt.reply_to_role
      ? {
          ...(existing?.replyTo?.messageId === receipt.reply_to_message_id ? existing.replyTo : {}),
          messageId: receipt.reply_to_message_id,
          role: receipt.reply_to_role,
          excerpt: receipt.quote_excerpt ?? "",
          selectedText: receipt.reply_to_excerpt ?? undefined,
        }
      : undefined;

  return {
    ...existing,
    id: existing?.id ?? receipt.client_queue_id,
    clientQueueId: receipt.client_queue_id,
    receiptConversationId: receipt.conversation_id,
    acceptedQueueId: receipt.id,
    receiptState: receipt.state,
    steeringRunId: receipt.steering_run_id ?? undefined,
    agentId: receipt.agent_id,
    content: receipt.content,
    fileIds,
    files: filesMatch ? existing?.files : undefined,
    mentions,
    ...(replyTo ? { replyTo } : { replyTo: undefined }),
    submission: {
      agentId: receipt.agent_id,
      pageContext: receipt.page_context,
      local: {
        payload: localTarget,
        fileRoot: localFolder && localTarget?.computer_grant == null ? localFolder : null,
        projectId: localProjectId,
      },
    },
    accepting: false,
    receiptAcceptanceAttempted: undefined,
    receiptReconciliationPending: undefined,
    transferring: false,
    receiptError: undefined,
    receiptErrorAction: undefined,
    transferError: undefined,
    transferErrorAction: undefined,
    receiptUnsupported: undefined,
    cancelRequested: undefined,
    refused: undefined,
  };
}

/** A row is drainable only after its owner-scoped receipt is confirmed pending. */
export function queueMayDrain(message: QueuedMessage | undefined, receiptMode: boolean): boolean {
  if (
    !message ||
    message.refused !== undefined ||
    message.receiptReconciliationPending ||
    message.accepting ||
    message.transferring ||
    message.receiptError !== undefined ||
    message.transferError !== undefined
  )
    return false;
  if (!receiptMode) return message.acceptedQueueId === undefined;
  if (
    message.receiptUnsupported ||
    !message.agentId ||
    !isUuid(message.clientQueueId ?? "") ||
    !isUuid(message.acceptedQueueId ?? "")
  )
    return false;
  return message.acceptedQueueId !== undefined && message.receiptState === "pending";
}

/** Only plain text for the agent running in this chat can be steered in-place. */
export function queueMaySteer(
  message: QueuedMessage | undefined,
  liveAgentId: string | null | undefined,
  receiptMode: boolean,
): boolean {
  if (
    !message ||
    !receiptMode ||
    !liveAgentId ||
    (message.agentId ?? message.submission?.agentId) !== liveAgentId ||
    !isUuid(message.acceptedQueueId ?? "") ||
    message.receiptState !== "pending" ||
    message.receiptReconciliationPending ||
    message.refused !== undefined ||
    message.accepting ||
    message.transferring ||
    message.cancelRequested ||
    message.receiptError !== undefined ||
    message.receiptErrorAction !== undefined ||
    message.receiptUnsupported ||
    message.transferError !== undefined ||
    message.fileIds?.length ||
    message.files?.length ||
    message.mentions?.length ||
    message.replyTo !== undefined ||
    message.submission?.pageContext != null ||
    message.submission?.local?.payload != null ||
    message.submission?.local?.fileRoot != null ||
    message.submission?.local?.projectId != null
  )
    return false;
  return true;
}

export type QueueTaskUnavailableReason = "computer_grant" | "device_id" | "routine_grant";

export function queueTaskUnavailableReason(
  message: QueuedMessage,
): QueueTaskUnavailableReason | null {
  const local = message.submission?.local?.payload;
  if (!local) return null;
  if (local.computer_grant != null) return "computer_grant";
  if (local.routine_grant != null) return "routine_grant";
  if (!local.device_id) return "device_id";
  return null;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
