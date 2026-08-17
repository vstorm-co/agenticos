import { storedUsage } from "./message-usage";
import type { ChatMessage, ChatMessageFile, MessagePart, ToolCall } from "@/types";

/**
 * Shape of a persisted message as returned by the backend (MessageRead).
 * Both the conversation history endpoint and the public demo endpoint return this.
 */
export interface RawToolCall {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: string;
}

/** One entry of a stored timeline - see `MessagePart` in the backend schemas. */
export interface RawMessagePart {
  type: "text" | "thinking" | "tool";
  text?: string | null;
  tool_call_id?: string | null;
}

export interface RawMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  /** The configured agent that answered. Null for the general assistant. */
  agent_id?: string | null;
  /** The run that produced this turn. Null for a turn written outside one. */
  run_id?: string | null;
  run_status?: string | null;
  /** The version number of the frozen spec that produced it. */
  agent_version?: number | null;
  tool_calls?: RawToolCall[] | null;
  thinking?: string | null;
  /**
   * The turn's timeline, in the order it happened.
   *
   * Null on a user turn, on a turn of a single part, and on any assistant turn
   * written before the backend recorded this - which is what
   * `buildAssistantParts` is still here for.
   */
  parts?: RawMessagePart[] | null;
  user_rating?: number | null;
  rating_count?: { likes: number; dislikes: number } | null;
  files?: ChatMessageFile[] | null;
  /** What the turn cost. Absent on a message written before it was recorded. */
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: string | null;
}

/**
 * Replay a stored timeline exactly as it happened.
 *
 * This is the path that makes a reopened conversation the one somebody watched:
 * the backend records the order it streamed (`MessagePart`), so there is nothing
 * to infer. A turn that wrote an introduction, drew three charts and then
 * summarised them comes back in that order, with both blocks of text.
 *
 * A `tool` entry names a call in `tool_calls` rather than repeating it. One
 * naming a call that is not there is dropped: the two are written in the same
 * transaction, so it means a call was deleted from under the timeline, and half
 * a step is worse than a missing one.
 */
export function replayStoredParts(
  stored: RawMessagePart[],
  toolCalls: ToolCall[],
  msgId: string,
): MessagePart[] {
  const byId = new Map(toolCalls.map((tc) => [tc.id, tc]));
  const parts: MessagePart[] = [];
  stored.forEach((entry, index) => {
    if (entry.type === "tool") {
      const toolCall = entry.tool_call_id ? byId.get(entry.tool_call_id) : undefined;
      if (toolCall) parts.push({ id: toolCall.id, type: "tool" as const, toolCall });
      return;
    }
    if (!entry.text) return;
    // Indexed, because a turn has more than one block of each kind - that is the
    // whole point of storing the order - and `${msgId}-text` twice is one React
    // key for two rows.
    parts.push({ id: `${msgId}-${entry.type}-${index}`, type: entry.type, content: entry.text });
  });
  return parts;
}

/**
 * Rebuild a plausible timeline for a turn whose real one was never recorded.
 *
 * The fallback, not the path: assistant turns written before the backend stored
 * `parts` have flat fields and no interleaving, so the best available guess is
 * reasoning, then the tools, then the answer. It is wrong for any turn that
 * spoke between its tool calls, and that cannot be fixed here - the text was
 * never saved. `replayStoredParts` is what runs for anything written since.
 */
export function buildAssistantParts(
  toolCalls: ToolCall[],
  content: string,
  msgId: string,
  thinking?: string | null,
): MessagePart[] {
  const parts: MessagePart[] = [];
  if (thinking) {
    parts.push({ id: `${msgId}-thinking`, type: "thinking" as const, content: thinking });
  }
  for (const tc of toolCalls) {
    parts.push({ id: tc.id, type: "tool" as const, toolCall: tc });
  }
  if (content) parts.push({ id: `${msgId}-text`, type: "text" as const, content });
  return parts;
}

/**
 * What a stored tool call's status means once the conversation is being read back.
 *
 * `failed` is this repository's word for the state the chat calls `error`.
 *
 * A call still marked *running* is the interesting one. Nothing on this screen can
 * finish it: the frames that would have are long gone, and some rows never get an
 * outcome at all - a run that broke while a tool was in flight. Left as `running`
 * the step pulsed forever under a conversation that ended days ago, in the present
 * tense, promising a result that was never coming. So a replayed call in flight is
 * `unfinished`: not an error, not a success, just the outcome nobody wrote down.
 *
 * A stored *awaiting_approval* passes through unchanged, and must (#601): the run
 * parked on that call and a person can still decide it, so it is a present-tense
 * state rather than an unwritten outcome. It does not outlive the run either way -
 * a resume settles the row with what the call returned, an expiry settles it with
 * the timeout notice.
 */
function replayedStatus(stored: string): ToolCall["status"] {
  if (stored === "failed") return "error";
  if (stored === "running" || stored === "pending") return "unfinished";
  return stored as ToolCall["status"];
}

export function conversationMessageToChatMessage(msg: RawMessage): ChatMessage {
  const toolCalls: ToolCall[] | undefined = msg.tool_calls?.map((tc) => ({
    id: tc.tool_call_id,
    name: tc.tool_name,
    args: tc.args,
    result: tc.result,
    status: replayedStatus(tc.status),
  }));

  const parts: MessagePart[] | undefined =
    msg.role !== "assistant"
      ? undefined
      : msg.parts && msg.parts.length > 0
        ? replayStoredParts(msg.parts, toolCalls ?? [], msg.id)
        : buildAssistantParts(toolCalls ?? [], msg.content, msg.id, msg.thinking);

  const files = Array.isArray(msg.files) ? msg.files : undefined;

  return {
    id: msg.id,
    role: msg.role,
    content: msg.content,
    thinking: msg.thinking ?? undefined,
    timestamp: new Date(msg.created_at),
    conversationId: msg.conversation_id,
    agentId: msg.agent_id ?? undefined,
    agentVersion: msg.agent_version ?? undefined,
    runId: msg.run_id ?? undefined,
    // Only the one worth drawing. A completed run needs no marker, and a run
    // still going has no answer on screen to mark.
    wasStopped: msg.run_status === "cancelled",
    usage: storedUsage(msg) ?? undefined,
    toolCalls,
    parts,
    user_rating: msg.user_rating ?? undefined,
    rating_count: msg.rating_count ?? undefined,
    files,
    fileIds: files?.map((f) => f.id),
  };
}

export function conversationMessagesToChatMessages(msgs: RawMessage[]): ChatMessage[] {
  return msgs.map(conversationMessageToChatMessage);
}
