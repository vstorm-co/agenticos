import {
  acceptedQueuedMessagesApi,
  type AcceptedQueueTask,
  type AcceptedQueuedMessageReceipt,
} from "@/lib/accepted-queued-messages-api";

export type AcceptedQueueTransferOutcome =
  | { kind: "task"; task: AcceptedQueueTask }
  | { kind: "sent" | "steered" | "cancelled" }
  | { kind: "pending" | "steering"; error: unknown }
  | { kind: "unknown"; error: unknown };

export type AcceptedQueueCancelOutcome =
  | { kind: "task"; task: AcceptedQueueTask }
  | { kind: "sent" | "steered" | "cancelled" }
  | { kind: "pending" | "steering"; error: unknown }
  | { kind: "unknown"; error: unknown };

function taskFromReceipt(receipt: AcceptedQueuedMessageReceipt): AcceptedQueueTask {
  return {
    id: receipt.task_id ?? "",
    conversation_id: receipt.task_conversation_id ?? "",
    status: "queued",
  };
}

function outcomeFromReceipt(
  receipt: AcceptedQueuedMessageReceipt,
  error?: unknown,
): AcceptedQueueTransferOutcome {
  if (receipt.state === "task") {
    const task = taskFromReceipt(receipt);
    if (task.id && task.conversation_id) return { kind: "task", task };
    return { kind: "unknown", error: error ?? new Error() };
  }
  if (receipt.state === "sent" || receipt.state === "steered" || receipt.state === "cancelled") {
    return { kind: receipt.state };
  }
  return { kind: receipt.state, error: error ?? new Error() };
}

/** Resolve lost Run-as-task responses against the owner-scoped receipt. */
export async function transferAcceptedQueueItem(
  conversationId: string,
  receiptId: string,
): Promise<AcceptedQueueTransferOutcome> {
  try {
    const task = await acceptedQueuedMessagesApi.runAsTask(conversationId, receiptId);
    if (task.id && task.conversation_id) return { kind: "task", task };
    try {
      const receipt = await acceptedQueuedMessagesApi.get(conversationId, receiptId);
      return outcomeFromReceipt(receipt, new Error());
    } catch {
      return { kind: "unknown", error: new Error() };
    }
  } catch (error) {
    try {
      const receipt = await acceptedQueuedMessagesApi.get(conversationId, receiptId);
      return outcomeFromReceipt(receipt, error);
    } catch {
      return { kind: "unknown", error };
    }
  }
}

/** Remove the browser row only after the receipt confirms its disposition. */
export async function cancelAcceptedQueueItem(
  conversationId: string,
  receiptId: string,
): Promise<AcceptedQueueCancelOutcome> {
  try {
    const receipt = await acceptedQueuedMessagesApi.cancel(conversationId, receiptId);
    return outcomeFromReceipt(receipt);
  } catch (error) {
    try {
      const receipt = await acceptedQueuedMessagesApi.get(conversationId, receiptId);
      return outcomeFromReceipt(receipt, error);
    } catch {
      return { kind: "unknown", error };
    }
  }
}
