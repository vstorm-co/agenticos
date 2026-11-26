import { apiClient } from "./api-client";
import type {
  Conversation,
  ConversationListResponse,
  ConversationMessagesResponse,
} from "@/types/conversation";
import type {
  RoomThreadContextActionRead,
  RoomThreadContextCandidateMessage,
  RoomThreadContextCandidatesRead,
  RoomThreadContextMutationInput,
  RoomThreadContextRangeInput,
  RoomThreadContextSearchCursor,
  RoomThreadContextSearchPage,
  RoomThreadContextSourcePage,
  RoomThreadContextUpdateInput,
} from "@/types/room-thread-context";

const conversationPath = (conversationId: string) =>
  "/conversations/" + encodeURIComponent(conversationId);

const threadPath = (conversationId: string, rootMessageId: string) =>
  conversationPath(conversationId) + "/room-threads/" + encodeURIComponent(rootMessageId);

export async function searchRoomThreadContextConversations(
  term: string,
  cursor: RoomThreadContextSearchCursor,
): Promise<RoomThreadContextSearchPage> {
  const normalized = term.trim().toLocaleLowerCase();
  const ownedLimit = 30;
  const sharedLimit = 50;
  const roomsLimit = 50;
  const [owned, shared, rooms] = await Promise.all([
    cursor.ownedSkip === null
      ? Promise.resolve(null)
      : (() => {
          const params = new URLSearchParams({
            limit: String(ownedLimit),
            skip: String(cursor.ownedSkip),
            sort_by: "updated_at",
            sort_dir: "desc",
            include_archived: "true",
            search: term.trim(),
          });
          return apiClient.get<ConversationListResponse>("/conversations?" + params.toString());
        })(),
    cursor.sharedSkip === null
      ? Promise.resolve(null)
      : apiClient.get<ConversationListResponse>(
          `/conversations/shared-with-me?skip=${cursor.sharedSkip}&limit=${sharedLimit}&include_archived=false`,
        ),
    cursor.roomsSkip === null
      ? Promise.resolve(null)
      : apiClient.get<ConversationListResponse>(
          `/conversations/rooms?skip=${cursor.roomsSkip}&limit=${roomsLimit}`,
        ),
  ]);
  const matches = new Map<string, Conversation>();
  for (const conversation of owned?.items ?? []) matches.set(conversation.id, conversation);
  for (const conversation of shared?.items ?? []) {
    if (
      !conversation.is_archived &&
      (conversation.title ?? "").toLocaleLowerCase().includes(normalized)
    ) {
      matches.set(conversation.id, matches.get(conversation.id) ?? conversation);
    }
  }
  for (const conversation of rooms?.items ?? []) {
    const isRoom = conversation.room_visibility != null || conversation.project_id != null;
    if (isRoom && (conversation.title ?? "").toLocaleLowerCase().includes(normalized)) {
      matches.set(conversation.id, matches.get(conversation.id) ?? conversation);
    }
  }
  const items = [...matches.values()].sort(
    (left, right) =>
      Date.parse(right.updated_at ?? right.created_at) -
      Date.parse(left.updated_at ?? left.created_at),
  );
  const nextCursor: RoomThreadContextSearchCursor = {
    ownedSkip:
      owned !== null &&
      owned.items.length > 0 &&
      cursor.ownedSkip !== null &&
      cursor.ownedSkip + owned.items.length < owned.total
        ? cursor.ownedSkip + owned.items.length
        : null,
    sharedSkip:
      shared !== null &&
      shared.items.length > 0 &&
      cursor.sharedSkip !== null &&
      cursor.sharedSkip + shared.items.length < shared.total
        ? cursor.sharedSkip + shared.items.length
        : null,
    roomsSkip:
      rooms !== null &&
      rooms.items.length > 0 &&
      cursor.roomsSkip !== null &&
      cursor.roomsSkip + rooms.items.length < rooms.total
        ? cursor.roomsSkip + rooms.items.length
        : null,
  };
  return {
    items,
    nextCursor:
      nextCursor.ownedSkip === null &&
      nextCursor.sharedSkip === null &&
      nextCursor.roomsSkip === null
        ? null
        : nextCursor,
  };
}

export async function getRoomThreadContextSourceConversation(
  conversationId: string,
): Promise<Conversation> {
  const result = await apiClient.get<Conversation>(conversationPath(conversationId) + "/metadata");
  if (result.id !== conversationId) throw new Error("ROOM_THREAD_CONTEXT_SOURCE_SCOPE_MISMATCH");
  return result;
}

function assertActionScope(
  result: RoomThreadContextActionRead,
  conversationId: string,
  rootMessageId?: string,
): void {
  const context = result.context;
  if (
    result.conversation_id !== conversationId ||
    (rootMessageId !== undefined && result.root_message_id !== rootMessageId) ||
    context === null ||
    context === undefined ||
    typeof context.source_conversation_id !== "string" ||
    context.source_conversation_id.length === 0
  ) {
    throw new Error("ROOM_THREAD_CONTEXT_SCOPE_MISMATCH");
  }
}

export async function getRoomThreadContextSourcePage(
  sourceConversationId: string,
  before: string | null = null,
): Promise<RoomThreadContextSourcePage> {
  const params = new URLSearchParams({
    latest: "true",
    limit: "101",
    top_level_only: "true",
  });
  if (before !== null) params.set("before", before);
  const page = await apiClient.get<ConversationMessagesResponse>(
    conversationPath(sourceConversationId) + "/messages?" + params.toString(),
  );
  if (
    page.items.some(
      (item) =>
        item.conversation_id !== sourceConversationId || item.thread_root_message_id != null,
    )
  ) {
    throw new Error("ROOM_THREAD_CONTEXT_SOURCE_SCOPE_MISMATCH");
  }
  const pageSize = 101;
  return {
    items: page.items.filter((item) => item.role === "user" || item.role === "assistant"),
    total: page.total,
    rawCount: page.items.length,
    nextCursor: page.items.length === pageSize ? (page.items[0]?.id ?? null) : null,
  };
}

export async function getRoomThreadContextCandidates(
  conversationId: string,
  rootMessageId: string,
): Promise<RoomThreadContextCandidatesRead> {
  const result = await apiClient.get<RoomThreadContextCandidatesRead>(
    threadPath(conversationId, rootMessageId) + "/context/candidates",
  );
  const ids = new Set<string>();
  if (
    !Array.isArray(result.items) ||
    typeof result.source_conversation_id !== "string" ||
    result.source_conversation_id.length === 0 ||
    result.items.length > 1000 ||
    result.total !== result.items.length ||
    result.items.some((item) => {
      if (
        item.conversation_id !== result.source_conversation_id ||
        item.role === "system" ||
        (item.deleted_at != null && item.deleted_at !== "") ||
        (item.thread_root_message_id != null && item.thread_root_message_id !== rootMessageId) ||
        ids.has(item.id)
      ) {
        return true;
      }
      ids.add(item.id);
      return false;
    })
  ) {
    throw new Error("ROOM_THREAD_CONTEXT_CANDIDATES_SCOPE_MISMATCH");
  }
  return result;
}

export async function createRoomThreadFromRange(
  conversationId: string,
  input: RoomThreadContextRangeInput,
): Promise<RoomThreadContextActionRead> {
  const result = await apiClient.post<RoomThreadContextActionRead>(
    conversationPath(conversationId) + "/room-threads",
    input,
  );
  assertActionScope(result, conversationId);
  if (result.context.source_conversation_id !== (input.source_conversation_id ?? conversationId)) {
    throw new Error("ROOM_THREAD_CONTEXT_SOURCE_MISMATCH");
  }
  return result;
}

export async function updateRoomThreadContext(
  conversationId: string,
  rootMessageId: string,
  input: RoomThreadContextUpdateInput,
): Promise<RoomThreadContextActionRead> {
  const result = await apiClient.patch<RoomThreadContextActionRead>(
    threadPath(conversationId, rootMessageId) + "/context",
    input,
  );
  assertActionScope(result, conversationId, rootMessageId);
  if (
    input.source_conversation_id !== undefined &&
    result.context.source_conversation_id !== input.source_conversation_id
  ) {
    throw new Error("ROOM_THREAD_CONTEXT_SOURCE_MISMATCH");
  }
  return result;
}

export async function moveRoomThreadContext(
  conversationId: string,
  rootMessageId: string,
  input: RoomThreadContextMutationInput,
): Promise<RoomThreadContextActionRead> {
  const result = await apiClient.post<RoomThreadContextActionRead>(
    threadPath(conversationId, rootMessageId) + "/context/move",
    input,
  );
  assertActionScope(result, conversationId, rootMessageId);
  if (!result.context.moved) throw new Error("ROOM_THREAD_CONTEXT_MOVE_NOT_CONFIRMED");
  return result;
}

export async function returnRoomThreadContext(
  conversationId: string,
  rootMessageId: string,
  input: RoomThreadContextMutationInput,
): Promise<RoomThreadContextActionRead> {
  const result = await apiClient.post<RoomThreadContextActionRead>(
    threadPath(conversationId, rootMessageId) + "/context/return",
    input,
  );
  assertActionScope(result, conversationId, rootMessageId);
  if (result.context.moved) throw new Error("ROOM_THREAD_CONTEXT_RETURN_NOT_CONFIRMED");
  return result;
}

export type { RoomThreadContextCandidateMessage };
