import { apiClient } from "@/lib/api-client";
import type { AssistantPageContext } from "@/lib/assistant-page-context";
import type { MentionRef } from "@/types/mention";

export type AcceptedQueuedMessageState =
  "pending" | "steering" | "steered" | "sent" | "task" | "cancelled";

export interface AcceptedQueuedMessagePayload {
  client_queue_id: string;
  agent_id: string;
  content: string;
  file_ids: string[];
  mentions: MentionRef[];
  reply_to_message_id: string | null;
  reply_to_excerpt: string | null;
  page_context: AssistantPageContext | null;
  local_target: Record<string, unknown> | null;
}

export interface AcceptedQueuedMessageReceipt extends AcceptedQueuedMessagePayload {
  id: string;
  conversation_id: string;
  state: AcceptedQueuedMessageState;
  message_id: string | null;
  task_id: string | null;
  task_conversation_id?: string | null;
  steering_run_id?: string | null;
  reply_to_role: "user" | "assistant" | null;
  quote_excerpt: string | null;
  created_at: string;
}

export interface AcceptedQueuedMessagePage {
  items: AcceptedQueuedMessageReceipt[];
  next_cursor: string | null;
}

export interface AcceptedQueueTask {
  id: string;
  conversation_id: string;
  status: string;
}

export function newQueueClientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (part) => {
    const value = Math.floor(Math.random() * 16);
    return (part === "x" ? value : (value & 0x3) | 0x8).toString(16);
  });
}

const base = (conversationId: string) =>
  `/conversations/${encodeURIComponent(conversationId)}/queued-messages`;

export const acceptedQueuedMessagesApi = {
  accept(conversationId: string, payload: AcceptedQueuedMessagePayload) {
    return apiClient.post<AcceptedQueuedMessageReceipt>(base(conversationId), payload);
  },
  list(conversationId: string, signal?: AbortSignal, cursor?: string) {
    return apiClient.get<AcceptedQueuedMessagePage>(base(conversationId), {
      signal,
      ...(cursor ? { params: { cursor } } : {}),
    });
  },
  get(conversationId: string, receiptId: string) {
    return apiClient.get<AcceptedQueuedMessageReceipt>(
      `${base(conversationId)}/${encodeURIComponent(receiptId)}`,
    );
  },
  cancel(conversationId: string, receiptId: string) {
    return apiClient.delete<AcceptedQueuedMessageReceipt>(
      `${base(conversationId)}/${encodeURIComponent(receiptId)}`,
    );
  },
  runAsTask(conversationId: string, receiptId: string) {
    return apiClient.post<AcceptedQueueTask>(
      `${base(conversationId)}/${encodeURIComponent(receiptId)}/run-as-task`,
    );
  },
};

/** Load every unresolved receipt before the client treats the server outbox as reconciled. */
export async function listAcceptedQueuedMessages(
  conversationId: string,
  signal?: AbortSignal,
): Promise<AcceptedQueuedMessageReceipt[]> {
  const items: AcceptedQueuedMessageReceipt[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await acceptedQueuedMessagesApi.list(conversationId, signal, cursor);
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
    if (cursor && seenCursors.has(cursor)) throw new Error();
    if (cursor) seenCursors.add(cursor);
  } while (cursor);
  return items;
}
