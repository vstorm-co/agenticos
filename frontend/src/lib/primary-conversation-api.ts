/**
 * The stable private conversation a person has with one agent (#2575).
 *
 * The same one every time for the same person and agent; the server creates it on
 * first use and answers 404 for an agent the caller may not see.
 */

import { apiClient } from "./api-client";

export async function openPrimaryConversation(agentId: string): Promise<string> {
  const answer = await apiClient.post<{ conversation_id: string }>(
    `/agents/${agentId}/primary-conversation`,
    {},
  );
  return answer.conversation_id;
}
