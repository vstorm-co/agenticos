import type { Conversation, ConversationMessage } from "./conversation";

export type RoomThreadContextState = "open" | "closed" | "archived";

export interface RoomThreadContextRead {
  source_conversation_id: string;
  start_message_id: string;
  end_message_id: string;
  first_ordinal: number;
  last_ordinal: number;
  excluded_message_ids: string[];
  message_ids: string[];
  message_count: number;
  moved: boolean;
  revision: number;
  /** True when a saved snapshot references a message that is no longer available. */
  stale?: boolean;
}

export interface RoomThreadContextCandidateMessage extends ConversationMessage {
  ordinal?: number | null;
  deleted_at?: string | null;
}

export interface RoomThreadContextCandidatesRead {
  source_conversation_id: string;
  items: RoomThreadContextCandidateMessage[];
  total: number;
}

export interface RoomThreadContextActionRead {
  conversation_id: string;
  root_message_id: string;
  state: RoomThreadContextState;
  following: boolean;
  unread: number;
  can_manage: boolean;
  context: RoomThreadContextRead;
}

export interface RoomThreadMovedStub {
  root_message_id: string;
  source_conversation_id: string;
  first_ordinal: number;
  last_ordinal: number;
  message_count: number;
  title: string;
}

export interface RoomThreadContextSearchCursor {
  ownedSkip: number | null;
  sharedSkip: number | null;
  roomsSkip: number | null;
}

export interface RoomThreadContextSearchPage {
  items: Conversation[];
  nextCursor: RoomThreadContextSearchCursor | null;
}

/** A source page keeps its raw pagination cursor even when unsupported rows are hidden. */
export interface RoomThreadContextSourcePage {
  items: RoomThreadContextCandidateMessage[];
  total: number;
  rawCount: number;
  nextCursor: string | null;
}

export interface RoomThreadContextRangeInput {
  start_message_id: string;
  end_message_id: string;
  excluded_message_ids?: string[];
  title?: string;
  source_conversation_id?: string;
}

export interface RoomThreadContextUpdateInput extends Omit<RoomThreadContextRangeInput, "title"> {
  expected_context_revision: number;
  move?: boolean | null;
}

export interface RoomThreadContextMutationInput {
  expected_context_revision: number;
}
