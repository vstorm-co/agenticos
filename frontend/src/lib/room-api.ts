import { apiClient } from "./api-client";
import type { Conversation } from "@/types/conversation";
import type {
  RoomAgentRequest,
  RoomMessageCreate,
  RoomMessageResult,
  RoomRequestList,
  RoomThreadPage,
} from "@/types/room";

const roomPath = (conversationId: string) => `/conversations/${conversationId}`;

export function listRoomRequests(conversationId: string): Promise<RoomRequestList> {
  return apiClient.get(`${roomPath(conversationId)}/room-requests`);
}

/** Retrying an uncertain acknowledgement must reuse this exact input, including its id. */
export function postRoomMessage(
  conversationId: string,
  input: RoomMessageCreate,
): Promise<RoomMessageResult> {
  return apiClient.post(`${roomPath(conversationId)}/room-messages`, input);
}

export function cancelRoomRequest(
  conversationId: string,
  requestId: string,
): Promise<RoomAgentRequest> {
  return apiClient.post(`${roomPath(conversationId)}/room-requests/${requestId}/cancel`, {});
}

export function createTeamRoom(projectId: string, title: string): Promise<Conversation> {
  return apiClient.post("/conversations", { project_id: projectId, title });
}

export async function getRoomThread(
  conversationId: string,
  rootMessageId: string,
  before: string | null = null,
): Promise<RoomThreadPage> {
  const params = new URLSearchParams({ latest: "true", limit: "50" });
  if (before !== null) params.set("before", before);
  const page = await apiClient.get<RoomThreadPage>(
    `${roomPath(conversationId)}/room-threads/${encodeURIComponent(rootMessageId)}?${params}`,
  );
  if (
    page.root.id !== rootMessageId ||
    page.root.conversation_id !== conversationId ||
    page.root.thread_root_message_id != null ||
    page.root.role === "system" ||
    page.items.some(
      (item) =>
        item.conversation_id !== conversationId || item.thread_root_message_id !== rootMessageId,
    )
  ) {
    // The panel renders chat.roomThread.unavailable; this diagnostic stays machine-readable.
    throw new Error("ROOM_THREAD_SCOPE_MISMATCH");
  }
  return page;
}
