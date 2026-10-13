import { apiClient } from "./api-client";

import type { RatingValue } from "@/types/chat";

/**
 * Rate one assistant message, or clear a rating - through the shared client so
 * the calls carry the session and active-organization headers, and the rating
 * endpoints are visible to `query-keys.ts` rather than two raw `fetch`es in a
 * component (#563). The response body is not read: the chat reconciles its own
 * thumb counts in its store, and the dashboard summaries are invalidated.
 */
export function rateMessage(
  conversationId: string,
  messageId: string,
  body: { rating: RatingValue; comment: string | null },
): Promise<unknown> {
  return apiClient.post(
    `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/rate`,
    body,
  );
}

export function removeRating(conversationId: string, messageId: string): Promise<unknown> {
  return apiClient.delete(
    `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/rate`,
  );
}
