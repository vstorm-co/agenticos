import { apiClient } from "@/lib/api-client";

/** A matching turn and the chat/thread needed to open it in the transcript. */
export interface ConversationMessageSearchHit {
  conversation_id: string;
  message_id: string;
  thread_root_message_id: string | null;
  title: string | null;
  updated_at: string;
  matched_at: string;
  hits: number;
  /** Bounded `ts_headline` excerpt; matched terms are marked with `**`. */
  snippet: string;
  speaker_role: string;
  speaker_name: string | null;
}

/** Deep-link payload for the chat's message paging and room-thread selection. */
export interface ConversationMessageSearchTarget {
  conversationId: string;
  messageId: string;
  threadRootMessageId?: string;
}

/** Search readable transcripts, returning one best matching turn per conversation. */
export async function searchConversationMessages(
  query: string,
): Promise<ConversationMessageSearchHit[]> {
  return apiClient.get<ConversationMessageSearchHit[]>("/conversations/search/messages", {
    params: { query: query.trim() },
  });
}
