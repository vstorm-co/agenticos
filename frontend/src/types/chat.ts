export type MessageRole = "user" | "assistant" | "system";
/** Rating values for message feedback. */
export enum RatingValue {
  LIKE = 1,
  DISLIKE = -1,
}

export type UserRating = RatingValue.LIKE | RatingValue.DISLIKE | null;

export interface ChatMessageFile {
  id: string;
  filename: string;
  mime_type: string;
  /** "image" | "pdf" | "docx" | "text" - derived from MIME on upload. */
  file_type: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
  isStreaming?: boolean;
  /** Group ID for related messages in a multi-agent chain. */
  groupId?: string;
  /** IDs of attached files - kept for sending. Use `files` for rendering. */
  fileIds?: string[];
  /** Full file metadata for rendering attachments. */
  files?: ChatMessageFile[];
  /** Conversation ID for this message */
  conversationId?: string;
  /** The published agent that produced this assistant turn. Absent means the
   *  general assistant, which is what a turn sent without an `agent_id` runs.
   *  Recorded per message on both paths - live and reloaded - because the
   *  picker can be changed mid-conversation, and one agent per thread would
   *  relabel every earlier answer as whoever is selected now. */
  agentId?: string;
  /** Which frozen spec answered. An agent is rewritten; what it said then was
   *  said by one version of it, and a transcript that named only the agent
   *  attributed old words to today's instructions. */
  agentVersion?: number;
  /** True if message ID is a temporary nanoid, not yet replaced by server ID */
  isTemporaryId?: boolean;
  /** Current user's rating */
  user_rating?: UserRating;
  /** Aggregate rating counts */
  rating_count?: { likes: number; dislikes: number } | null;
  /** Reasoning trace from extended-thinking models. Rendered dimmed +
   *  collapsible above the final response. */
  thinking?: string;
  /** Ordered timeline of the assistant turn: reasoning, text and tool
   *  calls in the exact order they occurred. Rendered in sequence so a
   *  multi-step turn (think → tools → text → think → tools → text) shows
   *  correctly. `content`/`thinking`/`toolCalls` are kept in sync as
   *  flat aggregates for copy/persist/rating. */
  parts?: MessagePart[];
  /** What this turn cost, on the turn that cost it.
   *
   *  Live turns only, and deliberately: it is measured when the run finishes and
   *  is not persisted per message, so a reloaded conversation has none. Absent
   *  therefore means "not recorded", never "free". */
  usage?: TurnUsage;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: "pending" | "running" | "completed" | "error" | "awaiting_approval";
  /**
   * `awaiting_approval` is its own state, not a kind of running. A parked call
   * produces no result *ever* until somebody decides, so a spinner is a lie that
   * never resolves — which is what the card did before.
   */
}

/** The three kinds of segment a turn is built from, live and replayed alike. */
export type MessagePartType = "thinking" | "text" | "tool";

/** One ordered segment of an assistant turn. */
export interface MessagePart {
  id: string;
  type: MessagePartType;
  /** Text for "thinking"/"text" parts. */
  content?: string;
  /** Tool invocation for "tool" parts. */
  toolCall?: ToolCall;
}

export type ChartType = "line" | "bar" | "pie" | "area" | "scatter";

export interface ChartSeries {
  key: string;
  label?: string | null;
  color?: string | null;
}

export interface ChartStyle {
  palette?: string[] | null;
  grid?: boolean;
  legend?: boolean;
  x_label?: string | null;
  y_label?: string | null;
  stacked?: boolean;
}

/** Structured chart payload produced by the agent's `create_chart` tool. */
export interface ChartSpec {
  kind: "chart";
  chart_type: ChartType;
  title: string;
  data: Array<Record<string, unknown>>;
  x_key: string;
  series: ChartSeries[];
  style: ChartStyle;
}

/**
 * Every frame the dashboard chat WebSocket sends, and nothing else.
 *
 * One member per `send_event(...)` in `backend/app/services/agent_session.py` plus one
 * per literal in `app/agents/subagent_events.py`. That is an exact set rather than a
 * best guess: `agent_session.py` decides every frame this socket sends, and it is held
 * at 100% coverage and type-checked in the gate.
 *
 * Grouped by whether `use-chat.ts` reads a frame, because the flat list could not say.
 * `llm_started`, `llm_completed`, `todo_event`, `context_usage` and `context_compacted`
 * sat in it naming frames no surface has ever emitted - two of them with a live-looking
 * `case` arm and a test asserting it behaved - so the union read as "the frames that
 * exist" while being part contract and part wish, and the next person adding one could
 * not tell which. That is the note under the delegation frames below, from the other
 * side: the same union carried the warning it was violating.
 */
export type WSEventType =
  // Read by `use-chat.ts`.
  | "conversation_created"
  | "message_saved"
  | "model_request_start"
  | "text_delta"
  | "thinking_delta"
  | "tool_call"
  | "tool_result"
  | "final_result"
  | "complete"
  | "error"
  | "tool_approval_required"
  | "ask_user"
  // Sent on every turn and deliberately unread, because each only announces a step
  // the frame after it already carries: `model_request_start` opens the assistant
  // message, so `user_prompt`, `user_prompt_processed` and `part_start` have nothing
  // left to do, and `text_delta`/`tool_call` carry the content that `tool_call_delta`,
  // `call_tools_start` and `final_result_start` merely precede. Named anyway - they
  // are on the wire, and a union that omitted them would be as misleading in the
  // other direction. A run timeline is the surface that would read them.
  | "user_prompt"
  | "user_prompt_processed"
  | "part_start"
  | "call_tools_start"
  | "tool_call_delta"
  | "final_result_start"
  // One per literal in `app/agents/subagent_events.py`. They replace
  // `subagent_status` / `subagent_message`, which nothing ever emitted and
  // nothing ever handled - two vocabularies for one subsystem is how a client
  // ends up listening for a frame the server stopped sending.
  | "subagent_start"
  | "subagent_text_delta"
  | "subagent_thinking_delta"
  | "subagent_tool_call"
  | "subagent_tool_result"
  | "subagent_awaiting_approval"
  | "subagent_complete";

/**
 * What one turn cost, and how full the workspace behind it is.
 *
 * Numbers rather than a formatted line: the chat draws a bar and a tooltip, and a
 * server-composed string would have to be parsed back apart. `null` is "nothing
 * was measured", which is a different thing to draw from zero.
 */
export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  budget_percent: number | null;
  /** This agent's own monthly cap, which is the one an author can raise. */
  agent_budget_percent: number | null;
  sandbox: {
    kind: string;
    percent: number | null;
    bytes_used: number | null;
    bytes_limit: number | null;
    memory_bytes: number | null;
    memory_limit_bytes: number | null;
  } | null;
}

export interface WSEvent {
  type: WSEventType;
  data?: unknown;
  timestamp?: string;
}

/* `TextDeltaEvent`, `ToolCallEvent`, `ToolResultEvent` and `FinalResultEvent` stood
   here, one per-frame envelope apiece, and every one of them was wrong about the wire:
   `TextDeltaEvent` declared `data.delta` where `agent_session.py` has always sent
   `content`, and `ToolResultEvent` declared `tool_name` and `result` where it sends
   `tool_call_id` and `content`. Nothing imported any of the four, so nothing ever
   disagreed with them - `use-chat.ts` narrows each payload inline at the `case` that
   reads it, which is the only place that knows the shape. A type that misdescribes a
   frame and has no reader is the same defect as a `case` arm for a frame nobody sends:
   it makes the boundary look documented. `ChatState` went with them, unread since
   `stores/chat-store.ts` declared its own.

   Making `WSEvent` a discriminated union over correct payloads is still the honest
   version of this and still a different change - it rewrites every branch in the
   handler. Deleting four wrong ones is not that refactor. */

export interface ActionRequest {
  /** The `approvals` row. What a decision is recorded against. */
  id: string;
  /** The model's own id for the call, so the card drawn for it can be resolved. */
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
}

export interface ReviewConfig {
  tool_name: string;
  /** Whether to allow editing the tool arguments */
  allow_edit?: boolean;
  /** Maximum time to wait for decision (seconds) */
  timeout?: number;
}

export interface PendingApproval {
  actionRequests: ActionRequest[];
  reviewConfigs: ReviewConfig[];
  /** The run to continue once every call has been decided. */
  runId: string;
  /**
   * The turn the parked calls are drawn in, captured when the approval arrived.
   *
   * Not read off the live "current message" when the decision is made: the park is
   * followed immediately by `complete`, which ends the turn and clears that ref - so
   * by the time somebody clicks Approve there is no current message, every
   * `updateToolCallPart` is skipped, and the step sits at "waiting for approval"
   * forever while the run has in fact resumed and answered.
   */
  messageId: string | null;
}

export type DecisionType = "approve" | "edit" | "reject";

export interface Decision {
  type: DecisionType;
  editedAction?: {
    id: string;
    tool_name: string;
    args: Record<string, unknown>;
  };
}

export interface AskUserQuestion {
  question: string;
  options: string[];
  /** Whether the user may type a free-form answer instead of picking an option. */
  allowCustom: boolean;
}

export interface AskUserAnswer {
  answer: string;
  skipped: boolean;
}

/* `SubagentMessage` and `SubagentMessageType` stood here, the payload of the
   `subagent_message` event that this file used to declare. Nothing ever emitted it
   and nothing ever handled it, so removing that name from `WSEventType` left these
   two with no reader at all - and a second delegation vocabulary sitting beside the
   real one is precisely how a client ends up listening for a frame the server never
   sends.

   The rest of that vocabulary has now followed, for the same reason one frame at a
   time: `TodoEventFrame` was the payload of `todo_event`, and no backend surface has
   ever sent one - there is no todo subsystem in `backend/app/`, so `ResearchTodo` and
   `ResearchTodoStatus` described a wire that does not exist. `SubagentStatus` and
   `SubagentTaskStatus` outlived it only through `ResearchReplay`, which only
   `MessagePart.research` read, which nothing ever constructed: `conversation-to-chat.ts`
   builds `thinking`, `tool` and `text` parts and `message-item.tsx` renders those
   three. `ContextUsage` was the payload of `context_usage`, which nothing sends either.
   A delegation is `Delegation` and `SubagentFrame` below - that is the one vocabulary,
   and it is the one the backend actually speaks. */

/* ------------------------------------------------------------------------- *
 * Delegation - a second agent's whole conversation inside one turn of this one.
 *
 * The six frames below mirror `backend/app/agents/subagent_events.py` field for
 * field, and they are a discriminated union on `kind` for the same reason the
 * backend's is: a surface has to switch on it. A text delta appends, a tool call
 * opens a row, the terminal frame closes the panel and writes the cost.
 *
 * `WSEvent` above is left as `{ type; data?: unknown }` on purpose. Making the whole
 * envelope a union means rewriting all twenty-odd branches in `use-chat.ts`, which is
 * a refactor worth doing and not this one. (The dead per-event interfaces that used to
 * sit beside it, each declaring a payload the wire does not send, have gone - see the
 * note above `ActionRequest`.) So the union stops at the delegation payload: every
 * frame carries `kind` inside `data` as well as in the envelope's `type`, so
 * `data as SubagentFrame` narrows honestly from there.
 * ------------------------------------------------------------------------- */

/** Whether the parent waits for the delegate, or carries on while it works. */
export type SubagentMode = "sync" | "async";

interface SubagentFrameBase {
  /** Unique per delegation. What keeps three concurrent specialists apart. */
  task_id: string;
  /** The delegate or specialist name its author gave it. */
  subagent: string;
  /** 0 is a specialist this run's own agent called; 1 is one that specialist called. */
  depth: number;
}

/**
 * The whole of a specialist a model invented mid-run, carried so it can be kept.
 *
 * Present on the opening frame of a *dynamic* delegation and nowhere else: a
 * delegate is published and an inline specialist lives in its parent's spec, but
 * one a model wrote at run time is persisted nowhere, so this streamed copy is the
 * only place its definition is legible - and only while the run is on screen. It
 * mirrors the backend `SpecialistDefinition`, and is everything such a specialist
 * has: instructions and a model, no capabilities, knowledge or delegates.
 */
export interface SpecialistDefinition {
  description: string;
  instructions: string;
  /** The label of the model profile the specialist named, resolved on promotion. */
  model: string;
}

export interface SubagentStartFrame extends SubagentFrameBase {
  kind: "subagent_start";
  mode: SubagentMode;
  prompt: string;
  /**
   * The delegation this one was started from, null when the run's own agent made it.
   *
   * Read from the journal at `begin`, which is the only moment both delegations
   * exist, and it is what nests a panel without guessing. `depth` alone cannot:
   * two specialists running at once are both one level up from a nested start.
   */
  parent_task_id: string | null;
  /**
   * A dynamic specialist's definition, or null for a delegate or inline specialist.
   *
   * Set only for a specialist the model invented at run time - the one kind nothing
   * else keeps - so a surface can offer to promote it while the run is on screen.
   */
  specialist: SpecialistDefinition | null;
}

export interface SubagentTextDeltaFrame extends SubagentFrameBase {
  kind: "subagent_text_delta";
  delta: string;
}

export interface SubagentThinkingDeltaFrame extends SubagentFrameBase {
  kind: "subagent_thinking_delta";
  delta: string;
}

export interface SubagentToolCallFrame extends SubagentFrameBase {
  kind: "subagent_tool_call";
  tool_name: string;
  tool_call_id: string;
}

export interface SubagentToolResultFrame extends SubagentFrameBase {
  kind: "subagent_tool_result";
  tool_name: string;
  tool_call_id: string;
  /** False when the tool raised, which is all the frame carries about it. */
  ok: boolean;
}

export interface SubagentAwaitingApprovalFrame extends SubagentFrameBase {
  /**
   * A sync delegate stopped for a person; the answer is still coming.
   *
   * Not a `subagent_complete`: nothing is recorded and no cost is known yet - the
   * continuation writes the outcome when the person decides. It closes the panel
   * with a "waiting for a person" state so it stops reading "working", and carries
   * no cost or run id because there is none. See `SubagentAwaitingApproval` in
   * `backend/app/agents/subagent_events.py`.
   */
  kind: "subagent_awaiting_approval";
}

export interface SubagentCompleteFrame extends SubagentFrameBase {
  kind: "subagent_complete";
  status: "completed" | "failed" | "cancelled";
  /** Present for a delegation to a published agent, which gets a run row. */
  run_id: string | null;
  /** What this delegation added to the parent run's ledger, as a number. */
  cost_usd: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string | null;
}

export type SubagentFrame =
  | SubagentStartFrame
  | SubagentTextDeltaFrame
  | SubagentThinkingDeltaFrame
  | SubagentToolCallFrame
  | SubagentToolResultFrame
  | SubagentAwaitingApprovalFrame
  | SubagentCompleteFrame;

/**
 * `running` is this surface's own: no frame says it, the absence of a terminal one does.
 *
 * `awaiting_approval` is not terminal - the delegate stopped for a person and the
 * run can still resume it - but it closes the panel all the same, because a panel
 * reading "working" through a wait that may never end is the bug the state exists
 * to fix (agenticos#173).
 */
export type DelegationStatus =
  "running" | "completed" | "failed" | "cancelled" | "awaiting_approval";

/**
 * One of the delegate's own tool calls.
 *
 * A name and whether it worked, and nothing else - which is the contract, not a
 * rendering choice: `SubagentToolCall` carries no arguments and
 * `SubagentToolResult` carries no content, so a delegate's step is a line of
 * narration rather than something to open. `ok` is null until its result lands.
 */
export interface DelegationStep {
  id: string;
  name: string;
  ok: boolean | null;
}

/** One delegation, assembled from its frames - the thing a panel draws. */
export interface Delegation {
  taskId: string;
  subagent: string;
  depth: number;
  mode: SubagentMode;
  prompt: string;
  /**
   * The delegation this one was started from, or null at the top.
   *
   * Named by the start frame's `parent_task_id`, never inferred. See `parentIn` in
   * `lib/delegations.ts` for the two cases that read as a root panel instead.
   */
  parentTaskId: string | null;
  status: DelegationStatus;
  /**
   * The definition of a specialist the model invented, or null for anything already
   * keepable. Set from the start frame; what a "promote to a draft agent" action in
   * chat reads, and what its absence hides that action for. See `SpecialistDefinition`.
   */
  specialist: SpecialistDefinition | null;
  text: string;
  thinking: string;
  steps: DelegationStep[];
  /**
   * The run row the delegate produced, once it reports one, and null until then.
   *
   * Only a delegation to a published agent gets a run row, so it stays null for a
   * specialist defined inline on the parent's spec. Carried because it is the only
   * link between a panel and the run history entry behind it - see
   * `DelegationRecorder` in `backend/app/agents/capabilities/subagents/`.
   */
  runId: string | null;
  costUsd: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  error: string | null;
}
