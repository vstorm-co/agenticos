/**
 * What needs the signed-in person's attention, and settling it once (#2575).
 *
 * The Inbox row, the card in the chat and the push or mail are deliveries of one
 * outcome; acknowledging, resolving or muting it here closes them all.
 */

import { apiClient } from "./api-client";

export type OutcomeStatus = "open" | "acknowledged" | "resolved" | "muted";
export type OutcomeAction = "acknowledge" | "resolve" | "mute";

export interface Outcome {
  id: string;
  kind: string;
  summary: string;
  context_url: string | null;
  status: OutcomeStatus;
  source_conversation_id: string | null;
  created_at: string;
  settled_at: string | null;
  settled_via: string | null;
}

interface OutcomeList {
  items: Outcome[];
}

/** The person's open outcomes that came from one chat. */
export async function listConversationOutcomes(conversationId: string): Promise<Outcome[]> {
  const params = new URLSearchParams({ conversation_id: conversationId });
  return (await apiClient.get<OutcomeList>(`/outcomes?${params.toString()}`)).items;
}

/** Settle one outcome, saying where the person did it. */
export function settleOutcome(
  id: string,
  action: OutcomeAction,
  via: "inbox" | "chat",
): Promise<Outcome> {
  return apiClient.post<Outcome>(`/outcomes/${id}/settle`, { action, via });
}
