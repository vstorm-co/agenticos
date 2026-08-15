import { RatingValue, type ChatMessageFile, type UserRating } from "./chat";

/**
 * An agent that answered in a conversation.
 *
 * A list, never one: the picker can be changed mid-thread, so a conversation
 * can have been had with several agents in turn.
 */
export interface ConversationAgent {
  id: string;
  slug: string;
  name: string;
  has_avatar: boolean;
}

export interface Conversation {
  id: string;
  user_id?: string;
  title?: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  /** In the order they first answered. Empty means the general assistant. */
  agents?: ConversationAgent[];
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  thinking?: string | null;
  created_at: string;
  model_name?: string;
  tokens_used?: number;
  /**
   * What this turn cost, stored per message.
   *
   * Split because input and output are priced an order of magnitude apart, so one
   * total cannot say whether an answer was expensive because of a long context or a
   * long answer. Absent on any message written before the API recorded it, and on a
   * turn whose cost could not be read - which means "not recorded", never "free", so
   * a client draws nothing rather than zeroes.
   */
  input_tokens?: number | null;
  output_tokens?: number | null;
  /** A string, like every other money field the API returns: `Numeric` is serialized
   *  as one so a sum of a thousand turns cannot drift from the budget it is compared
   *  against. */
  cost_usd?: string | null;
  /**
   * Whether `cost_usd` is a floor rather than the whole of it.
   *
   * True when the turn reached a model with no price entry. Null on every
   * message written before it was recorded, which is "not recorded" rather than
   * "exact" - a client draws the caveat on `true` alone.
   */
  cost_is_partial?: boolean | null;
  /**
   * Tokens the history sent with this turn occupied, after any compaction.
   *
   * The count only: the window it is a share of belongs to the model answering
   * next, which the chat lets somebody switch between turns.
   */
  context_used_tokens?: number | null;
  /** Which configured agent answered. Null for the general assistant. */
  agent_id?: string | null;
  tool_calls?: ConversationToolCall[];
  files?: ChatMessageFile[];
  user_rating?: UserRating;
  rating_count?: { likes: number; dislikes: number } | null;
}

export interface ConversationToolCall {
  id: string;
  message_id: string;
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "pending" | "running" | "completed" | "failed";
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
}

export interface ConversationListResponse {
  items: Conversation[];
  total: number;
}

export interface ConversationWithMessages extends Conversation {
  messages: ConversationMessage[];
}
/**
 * Message rating types.
 */

export interface MessageRating {
  id: string;
  message_id: string;
  user_id: string;
  rating: RatingValue;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageRatingWithDetails extends MessageRating {
  message_content: string | null;
  message_role: string | null;
  conversation_id: string | null;
  user_email: string | null;
  user_name: string | null;
}

export interface MessageRatingListResponse {
  items: MessageRatingWithDetails[];
  total: number;
}

export interface RatingSummary {
  total_ratings: number;
  like_count: number;
  dislike_count: number;
  average_rating: number;
  with_comments: number;
  ratings_by_day: Array<{ date: string; likes: number; dislikes: number }>;
}

export interface ConversationShare {
  id: string;
  conversation_id: string;
  shared_by: string;
  shared_with?: string;
  share_token?: string;
  permission: "view" | "edit";
  shared_with_email?: string;
  shared_by_email?: string;
  created_at: string;
}

export interface ConversationShareListResponse {
  items: ConversationShare[];
  total: number;
}

export interface AdminConversation {
  id: string;
  user_id?: string;
  title?: string;
  is_archived: boolean;
  message_count: number;
  user_email?: string;
  agents?: ConversationAgent[];
  created_at: string;
  updated_at?: string;
}

export interface AdminConversationListResponse {
  items: AdminConversation[];
  total: number;
}

/**
 * One user as the deployment admin sees them - `AdminUserRead`, field for field.
 *
 * Field for field is the point. This is hand-written against a schema nothing
 * checks it against, and the copy that used to live in `use-admin-users.ts`
 * declared a `role: string` that the API stopped returning when `users.role` was
 * dropped in migration `0066` - so the users table drew a Role column that was
 * empty on every row, and TypeScript was happy because the type said otherwise.
 * There is one copy now, and `conversation_count` is in it because the backend
 * computes it with a join on every page load.
 */
export interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_app_admin: boolean;
  conversation_count: number;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
}
