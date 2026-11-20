import { apiClient } from "@/lib/api-client";

const PAGE_SIZE = 50;

export interface ConversationMessagePin {
  message_id: string;
  thread_root_message_id: string | null;
  role: "user" | "assistant" | "system";
  message_created_at: string;
  pinned_at: string;
  /** Bounded live excerpt; never stored in the pin row. */
  preview: string;
}

export interface ConversationMessagePinPage {
  items: ConversationMessagePin[];
  total: number;
}

const path = (conversationId: string) =>
  `/conversations/${encodeURIComponent(conversationId)}/message-pins`;
const messagePath = (conversationId: string, messageId: string) =>
  `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/pin`;

export async function listConversationMessagePins(
  conversationId: string,
  skip: number,
  signal?: AbortSignal,
): Promise<ConversationMessagePinPage> {
  return apiClient.get<ConversationMessagePinPage>(path(conversationId), {
    params: { skip: String(skip), limit: String(PAGE_SIZE) },
    signal,
  });
}

export async function pinConversationMessage(
  conversationId: string,
  messageId: string,
): Promise<ConversationMessagePin> {
  return apiClient.post<ConversationMessagePin>(messagePath(conversationId, messageId));
}

export async function unpinConversationMessage(
  conversationId: string,
  messageId: string,
): Promise<void> {
  await apiClient.delete<void>(messagePath(conversationId, messageId));
}
