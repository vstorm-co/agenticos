import { apiClient } from "./api-client";
import type { Conversation } from "@/types/conversation";
import type {
  RoomAgentRequest,
  RoomMessageCreate,
  RoomMessageResult,
  RoomRequestList,
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
