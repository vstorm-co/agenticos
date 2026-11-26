import type { ConversationMessage } from "./conversation";
import type { MessageReply } from "./chat";
import type { RawMessage } from "@/lib/conversation-to-chat";
import type { FileUploadResponse } from "@/lib/file-api";
import type { RoomThreadContextRead } from "./room-thread-context";

export type RoomRequestStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "awaiting_answer"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface RoomAgentRequest {
  id: string;
  message_id: string;
  conversation_id: string;
  requester_id: string;
  agent_id: string;
  status: RoomRequestStatus;
  run_id: string | null;
  error: string | null;
  created_at: string;
  /** How this request was selected; old rows were explicit responder picks. */
  dispatch?: "explicit" | "mention" | "automatic";
  thread_root_message_id?: string | null;
}

export interface RoomParticipantRef {
  kind: "user" | "agent";
  id: string;
}

export interface RoomParticipantRead extends RoomParticipantRef {
  name: string;
  avatar_url: string | null;
  is_member: boolean;
  can_add: boolean;
  can_mention: boolean;
  /** Only meaningful for agent participants. */
  auto_reply: boolean;
}

export interface RoomParticipantsRead {
  conversation_id: string;
  /** Null for an older project room, whose access is governed by project ACL. */
  visibility: "private" | "public" | null;
  can_post: boolean;
  can_manage: boolean;
  items: RoomParticipantRead[];
}

export interface RoomMentionablesRead {
  items: RoomParticipantRead[];
}

export interface CreateRoomConversationInput {
  title: string;
  visibility: "private" | "public";
  participants: RoomParticipantRef[];
}

export interface RoomRequestList {
  items: RoomAgentRequest[];
  total: number;
  /** The current project's use grant, independent of who created the chat. */
  can_post: boolean;
}

export interface RoomMessageCreate {
  client_message_id: string;
  content: string;
  reply_to_message_id?: string | null;
  reply_to_excerpt?: string | null;
  thread_root_message_id?: string | null;
  /** Legacy single-agent responder selection; retained for older clients. */
  agent_id?: string | null;
  /** Explicit room recipients. These are separate from single-agent resource mentions. */
  mentions?: RoomParticipantRef[];
  /** Uploaded files are linked atomically with this message before any agent runs. */
  file_ids?: string[];
  intent?: "message" | "ask_lead";
  expected_policy_revision?: number;
}

export interface RoomMessageResult {
  message: ConversationMessage;
  requests?: RoomAgentRequest[];
  /** Legacy first-request field. */
  request: RoomAgentRequest | null;
}

export interface RoomThreadPage {
  root: RawMessage;
  items: RawMessage[];
  total: number;
  can_post: boolean;
  state?: "open" | "closed" | "archived";
  can_manage?: boolean;
  following?: boolean;
  unread?: number;
  /** Included snapshot context, separate from the root and actual replies. */
  context?: RoomThreadContextRead | null;
  context_messages?: RawMessage[];
}

/** A browser draft and its frozen, possibly committed submission. Never persisted. */
export interface RoomDraft {
  content: string;
  roomMentions: RoomDraftMention[];
  attachments: FileUploadResponse[];
  pendingUploads: RoomPendingUpload[];
  uploadError: string | null;
  intent: "message" | "ask_lead";
  reply: MessageReply | null;
  attempt: { input: RoomMessageCreate; reply: MessageReply | null } | null;
  sending: boolean;
  error: string | null;
}

export interface RoomPendingUpload {
  id: string;
  name: string;
  size: number;
}

/** The exact visible token tied to one participant identity in a room draft. */
export interface RoomDraftMention extends RoomParticipantRef {
  name: string;
  start: number;
  end: number;
}
