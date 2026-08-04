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

export type MessagePartType = "thinking" | "text" | "tool" | "research";

export interface ResearchReplay {
  todos: ResearchTodo[];
  subagents: SubagentStatus[];
}

/** One ordered segment of an assistant turn. */
export interface MessagePart {
  id: string;
  type: MessagePartType;
  /** Text for "thinking"/"text" parts. */
  content?: string;
  /** Tool invocation for "tool" parts. */
  toolCall?: ToolCall;
  research?: ResearchReplay;
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

export type WSEventType =
  | "user_prompt"
  | "user_prompt_processed"
  | "model_request_start"
  | "part_start"
  | "text_delta"
  | "thinking_delta"
  | "tool_call_delta"
  | "call_tools_start"
  | "tool_call"
  | "tool_result"
  | "final_result_start"
  | "final_result"
  | "complete"
  | "error"
  | "conversation_created"
  | "message_saved"
  | "tool_approval_required"
  | "ask_user"
  | "todo_event"
  // One per literal in `app/agents/subagent_events.py`. They replace
  // `subagent_status` / `subagent_message`, which nothing ever emitted and
  // nothing ever handled - two vocabularies for one subsystem is how a client
  // ends up listening for a frame the server stopped sending.
  | "subagent_start"
  | "subagent_text_delta"
  | "subagent_thinking_delta"
  | "subagent_tool_call"
  | "subagent_tool_result"
  | "subagent_complete"
  | "context_usage"
  | "context_compacted"
  | "llm_started"
  | "llm_completed";

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

export interface TextDeltaEvent {
  type: "text_delta";
  data: {
    delta: string;
  };
}

export interface ToolCallEvent {
  type: "tool_call";
  data: {
    tool_name: string;
    args: Record<string, unknown>;
  };
}

export interface ToolResultEvent {
  type: "tool_result";
  data: {
    tool_name: string;
    result: unknown;
  };
}

export interface FinalResultEvent {
  type: "final_result";
  data: {
    output: string;
    tool_events: ToolCall[];
  };
}

export interface ChatState {
  messages: ChatMessage[];
  isConnected: boolean;
  isProcessing: boolean;
}

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

export interface ToolApprovalRequiredEvent {
  type: "tool_approval_required";
  data: {
    action_requests: ActionRequest[];
    review_configs: ReviewConfig[];
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

export interface AskUserEvent {
  type: "ask_user";
  data: {
    questions: { question: string; options: string[]; allow_custom: boolean }[];
  };
}

export type ResearchTodoStatus = "pending" | "in_progress" | "completed" | "blocked";

export interface ResearchTodo {
  id: string;
  content: string;
  status: ResearchTodoStatus;
  active_form: string;
  parent_id: string | null;
  depends_on: string[];
}

export interface TodoEventFrame {
  type: "todo_event";
  data: {
    event_type: "created" | "updated" | "status_changed" | "completed" | "deleted";
    todo: ResearchTodo;
    previous: ResearchTodo | null;
    ts: string | null;
  };
}

export type SubagentTaskStatus =
  "pending" | "running" | "waiting_for_answer" | "completed" | "failed" | "cancelled" | "retrying";

export interface SubagentStatus {
  task_id: string;
  subagent_name: string;
  description: string;
  status: SubagentTaskStatus;
  error: string | null;
  /** The subagent's returned findings (shown in the detailed research view). */
  result?: string | null;
}

/* `SubagentMessage` and `SubagentMessageType` stood here, the payload of the
   `subagent_message` event that this file used to declare. Nothing ever emitted it
   and nothing ever handled it, so removing that name from `WSEventType` left these
   two with no reader at all - and a second delegation vocabulary sitting beside the
   real one is precisely how a client ends up listening for a frame the server never
   sends. `SubagentStatus` above stays: `ResearchReplay` still references it. */

export interface ContextUsage {
  pct: number;
  current: number;
  max: number;
}

/* ------------------------------------------------------------------------- *
 * Delegation - a second agent's whole conversation inside one turn of this one.
 *
 * The six frames below mirror `backend/app/agents/subagent_events.py` field for
 * field, and they are a discriminated union on `kind` for the same reason the
 * backend's is: a surface has to switch on it. A text delta appends, a tool call
 * opens a row, the terminal frame closes the panel and writes the cost.
 *
 * `WSEvent` above is left as `{ type; data?: unknown }` on purpose. Making the
 * whole envelope a union means rewriting all twenty-odd branches in `use-chat.ts`
 * and deleting the dead per-event interfaces beside it - `TextDeltaEvent` declares
 * `data.delta` where the wire has always sent `content` - which is a refactor worth
 * doing and not this one. So the union stops at the delegation payload: every frame
 * carries `kind` inside `data` as well as in the envelope's `type`, so
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

export interface SubagentStartFrame extends SubagentFrameBase {
  kind: "subagent_start";
  mode: SubagentMode;
  prompt: string;
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
  | SubagentCompleteFrame;

/** `running` is this surface's own: no frame says it, the absence of a terminal one does. */
export type DelegationStatus = "running" | "completed" | "failed" | "cancelled";

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
   * Inferred, because no frame names a parent: a start at depth d belongs to the
   * most recent delegation at depth d-1 that has not finished. See `parentOf` in
   * `lib/delegations.ts`.
   */
  parentTaskId: string | null;
  status: DelegationStatus;
  text: string;
  thinking: string;
  steps: DelegationStep[];
  costUsd: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  error: string | null;
}
