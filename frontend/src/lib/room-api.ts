import { apiClient } from "./api-client";
import type { Conversation } from "@/types/conversation";
import type {
  RoomAgentRequest,
  CreateRoomConversationInput,
  RoomMessageCreate,
  RoomMessageResult,
  RoomMentionablesRead,
  RoomParticipantRead,
  RoomParticipantRef,
  RoomParticipantsRead,
  RoomRequestList,
  RoomThreadPage,
} from "@/types/room";
import type { ConversationListResponse } from "@/types/conversation";

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

export function getRoomParticipants(conversationId: string): Promise<RoomParticipantsRead> {
  return apiClient.get(`${roomPath(conversationId)}/participants`);
}

export function getRoomMentionables(conversationId: string): Promise<RoomMentionablesRead> {
  return apiClient.get(`${roomPath(conversationId)}/room-mentionables`);
}

export function addRoomParticipant(
  conversationId: string,
  participant: RoomParticipantRef,
): Promise<RoomParticipantRead> {
  return apiClient.post(`${roomPath(conversationId)}/participants`, participant);
}

export function removeRoomParticipant(
  conversationId: string,
  participant: RoomParticipantRef,
): Promise<void> {
  return apiClient.delete(
    `${roomPath(conversationId)}/participants/${participant.kind}/${encodeURIComponent(participant.id)}`,
  );
}

export function updateRoomAgentAutoReply(
  conversationId: string,
  agentId: string,
  autoReply: boolean,
): Promise<RoomParticipantRead> {
  return apiClient.patch(
    `${roomPath(conversationId)}/participants/agent/${encodeURIComponent(agentId)}`,
    { auto_reply: autoReply },
  );
}

export function createRoomConversation(input: CreateRoomConversationInput): Promise<Conversation> {
  return apiClient.post("/conversations/rooms", input);
}

export function getRoomDirectory(skip = 0, limit = 50): Promise<ConversationListResponse> {
  return apiClient.get("/conversations/rooms", {
    params: { skip: String(skip), limit: String(limit) },
  });
}

export function joinPublicRoom(conversationId: string): Promise<Conversation> {
  return apiClient.post(`${roomPath(conversationId)}/join`, {});
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
  const context = page.context ?? null;
  const contextIds = new Set(context?.message_ids ?? []);
  const contextMessageIds = new Set<string>();
  if (
    page.root.id !== rootMessageId ||
    page.root.conversation_id !== conversationId ||
    page.root.thread_root_message_id != null ||
    page.root.role === "system" ||
    page.items.some(
      (item) =>
        item.conversation_id !== conversationId || item.thread_root_message_id !== rootMessageId,
    ) ||
    (context !== null &&
      (context.source_conversation_id.length === 0 ||
        context.start_message_id.length === 0 ||
        context.end_message_id.length === 0 ||
        context.revision < 0 ||
        context.message_count !== context.message_ids.length)) ||
    (page.context_messages ?? []).some((item) => {
      const invalid =
        context === null ||
        item.conversation_id !== context.source_conversation_id ||
        item.role === "system" ||
        !contextIds.has(item.id) ||
        contextMessageIds.has(item.id);
      contextMessageIds.add(item.id);
      return invalid;
    })
  ) {
    // The panel renders chat.roomThread.unavailable; this diagnostic stays machine-readable.
    throw new Error("ROOM_THREAD_SCOPE_MISMATCH");
  }
  return page;
}

export type RoomThreadLifecycleAction = "close" | "reopen" | "archive" | "unarchive";

function roomThreadPath(conversationId: string, rootMessageId: string): string {
  return `${roomPath(conversationId)}/room-threads/${encodeURIComponent(rootMessageId)}`;
}

export function updateRoomThreadState(
  conversationId: string,
  rootMessageId: string,
  action: RoomThreadLifecycleAction,
): Promise<void> {
  return apiClient.post(`${roomThreadPath(conversationId, rootMessageId)}/${action}`, {});
}

export function followRoomThread(conversationId: string, rootMessageId: string): Promise<void> {
  return apiClient.put(`${roomThreadPath(conversationId, rootMessageId)}/follow`, {});
}

export function unfollowRoomThread(conversationId: string, rootMessageId: string): Promise<void> {
  return apiClient.delete(`${roomThreadPath(conversationId, rootMessageId)}/follow`);
}

export function markRoomThreadRead(
  conversationId: string,
  rootMessageId: string,
  throughMessageId: string,
): Promise<void> {
  return apiClient.post(`${roomThreadPath(conversationId, rootMessageId)}/read`, {
    through_message_id: throughMessageId,
  });
}
