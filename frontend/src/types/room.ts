import type { ConversationMessage } from "./conversation";

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
  /** Omitted for a human-only message; resource mentions never select a responder. */
  agent_id?: string | null;
}

export interface RoomMessageResult {
  message: ConversationMessage;
  request: RoomAgentRequest | null;
}
