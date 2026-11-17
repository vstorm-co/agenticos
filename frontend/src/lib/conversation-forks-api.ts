import { apiClient } from "@/lib/api-client";

/** A separately stored child conversation, opened in its own ChatScope. */
export interface ConversationForkRead {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  is_archived: boolean;
  forked_from: {
    conversation_id: string;
    message_id: string | null;
    title: string | null;
  };
}

export interface ConversationForkList {
  items: ConversationForkRead[];
  total: number;
}

/** List this owner's bounded page of personal child conversations. */
export async function listConversationForks(
  sourceId: string,
  messageId: string,
  { skip = 0, limit = 100 }: { skip?: number; limit?: number } = {},
): Promise<ConversationForkList> {
  return apiClient.get<ConversationForkList>(
    `/conversations/${encodeURIComponent(sourceId)}/forks`,
    { params: { message_id: messageId, skip: String(skip), limit: String(limit) } },
  );
}

/**
 * Create a fork without selecting it in the main chat or changing the URL.
 * The caller chooses whether and where the isolated child should be opened.
 */
export async function createConversationSideThread(
  sourceId: string,
  messageId: string,
): Promise<ConversationForkRead> {
  return apiClient.post<ConversationForkRead>(
    `/conversations/${encodeURIComponent(sourceId)}/fork`,
    { message_id: messageId },
  );
}
