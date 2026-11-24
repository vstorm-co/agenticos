import { apiClient } from "./api-client";
import type { RoomMessageReactionsRead } from "@/types/room-message-reaction";

const reactionPath = (conversationId: string, messageId: string) =>
  `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/reactions`;

/** Ensure this signed-in person has the emoji on the room message. */
export function setRoomMessageReaction(
  conversationId: string,
  messageId: string,
  emoji: string,
): Promise<RoomMessageReactionsRead> {
  return apiClient.put(reactionPath(conversationId, messageId), { emoji });
}

/** Ensure this signed-in person no longer has the emoji on the room message. */
export function removeRoomMessageReaction(
  conversationId: string,
  messageId: string,
  emoji: string,
): Promise<RoomMessageReactionsRead> {
  return apiClient.delete(reactionPath(conversationId, messageId), { body: { emoji } });
}
