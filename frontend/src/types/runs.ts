/** Types for run history, approvals and the cost dashboard. */

export type RunStatus =
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "awaiting_approval"
  | "budget_exceeded"
  | "guardrail_blocked";

export interface AgentRun {
  id: string;
  agent_id: string;
  agent_version_id: string | null;
  user_id: string | null;
  surface: string;
  status: RunStatus;
  model_label: string | null;
  /**
   * The vendor the model actually ran at, as the provider catalog spells it -
   * what the table keys a brand mark on. `model_label` names the profile; a
   * repointed profile can change vendor under the same label. Null for runs
   * recorded before it was tracked.
   */
  provider: string | null;
  input_tokens: number;
  output_tokens: number;
  /** Serialised Decimal - never parse into a float for arithmetic. */
  cost_usd: string;
  /** True when a model in this run had no price; the cost is a floor. */
  cost_is_partial: boolean;
  logfire_trace_id: string | null;
  /**
   * Where this run's trace can be read, resolved server-side. Sent on the
   * single-run read only - a list of fifty runs has no use for fifty trace
   * links - and null when nothing was tracing or nowhere is configured to
   * link to.
   */
  logfire_url?: string | null;
  /**
   * The runs either side of this one in its own conversation, by start time.
   * Sent on the single-run read only, like `logfire_url`; null at the thread's
   * edge, on a run that never started, and on a run with no conversation
   * behind it - an API call has no neighbours to step to.
   */
  prev_run_id?: string | null;
  next_run_id?: string | null;
  error: string | null;
  /**
   * Whether an assistant answer this run produced was rated down by anybody -
   * what run history draws a 👎 on, and the same fact `?rated=down` filters on.
   *
   * A rating hangs off a message and a message names its run, so a run older
   * than that stamping reads `false`. The backend computes it on the run reads;
   * it is `false` on any surface that does not, never absent.
   */
  down_rated: boolean;
  /**
   * The thread the run ran inside, or null when it ran with no conversation -
   * an API call, a resumed run. `AgentRunRead` has carried it all along; the
   * run table reads it to offer the chat behind a run (#765).
   */
  conversation_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  /**
   * The run this one was delegated from, or null for a run somebody started.
   *
   * The two must not be read the same way. Every run shares one spend ledger,
   * so a parent's `cost_usd` already contains its children's - a page that
   * interleaves them has a cost column nobody can add up, next to a
   * month-to-date figure that correctly counts the parent once. `GET /runs`
   * therefore lists only top-level runs unless `parent_run_id` asks for one
   * run's delegations, and this is how a row from that answer says so.
   */
  parent_run_id: string | null;
  /**
   * Which delegation produced this run - the `task_id` its `subagent_*` frames
   * carried, so a panel in a transcript and a row here are visibly one thing.
   *
   * Null whenever `parent_run_id` is: deleting a parent orphans the child, and
   * the backend withholds a handle whose transcript went with the parent rather
   * than sending one that reaches nothing.
   */
  subagent_task_id: string | null;
}

export interface AgentRunList {
  items: AgentRun[];
  total: number;
}

/**
 * One turn of a run's transcript, as `GET /runs/{run_id}/transcript` returns it.
 *
 * The wire is `MessageRead` plus the ratings, and has been all along - this
 * type under-declared it for months, which is why the run detail could only
 * ever show role and content while the steps, the reasoning and the tool calls
 * sat unread in the response. Declared structurally compatible with the
 * conversation reader's `RawMessage`, so the run timeline replays a turn with
 * the same machinery a reopened chat does.
 *
 * `user_rating` is the reading caller's own thumb (`1`/`-1`/absent),
 * `rating_count` the aggregate; `rating_comment` is the free text left with a
 * thumb down, which is the highest-signal half - a rating with words is a
 * complaint you can act on.
 */
export interface RunTranscriptMessage {
  id: string;
  role: string;
  content: string;
  created_at?: string;
  /**
   * The run that produced this turn. What tells the focused run's own turns
   * from the rest of the thread when the transcript is read conversation-wide.
   */
  run_id?: string | null;
  /** Reasoning trace, assistant turns only. */
  thinking?: string | null;
  /**
   * The turn's timeline in the order it happened - text, reasoning and tool
   * entries interleaved. Null on a user turn and on an assistant turn written
   * before it was recorded, which is the signal to reconstruct an order from
   * `content`, `thinking` and `tool_calls` instead.
   */
  parts?:
    | {
        type: "text" | "thinking" | "tool" | "ask_user";
        text?: string | null;
        tool_call_id?: string | null;
        question?: string | null;
        answer?: string | null;
      }[]
    | null;
  tool_calls?:
    | {
        tool_call_id: string;
        tool_name: string;
        args: Record<string, unknown>;
        result?: unknown;
        status: string;
      }[]
    | null;
  /**
   * The files that arrived with this turn, as `MessageRead.files` carries them.
   *
   * Declared here because they were being dropped: the wire has sent them since
   * attachments existed - the repository eager-loads them on every transcript
   * read - and the run detail rendered a question whose document was invisible,
   * which is the one thing an operator asking "what did the model actually get"
   * most needs to see.
   */
  files?: { id: string; filename: string; mime_type: string; file_type: string }[] | null;
  /** Which model answered this turn. A thread can change model between turns. */
  model_name?: string | null;
  /** The frozen spec's version number, where a published agent answered. */
  agent_version?: number | null;
  /**
   * How the run behind this turn ended, so a half-written answer from a
   * cancelled run does not read as a complete one.
   */
  run_status?: string | null;
  /** What this turn cost. Absent means not recorded, never free. */
  input_tokens?: number | null;
  output_tokens?: number | null;
  /** Serialised Decimal - a string on the wire, because money is `Numeric`. */
  cost_usd?: string | null;
  /** True when a model in this turn had no price entry: the figure is a floor. */
  cost_is_partial?: boolean | null;
  /** Tokens the history sent with this turn occupied, after any compaction. */
  context_used_tokens?: number | null;
  /** The current reader's own rating: 1 (up), -1 (down), or absent for none. */
  user_rating?: number | null;
  /** Aggregate counts across everyone who rated this answer. */
  rating_count?: { likes: number; dislikes: number } | null;
  /** The free-text comment left with a thumb down, when there was one. */
  rating_comment?: string | null;
}

/**
 * A run's recorded turns, newest question first.
 *
 * `conversation_id` is null for a run with no conversation behind it - an HTTP
 * API call, a resumed run - which is what lets the surface say "nothing was
 * recorded" rather than draw an empty transcript.
 */
export interface RunTranscript {
  run_id: string;
  conversation_id: string | null;
  items: RunTranscriptMessage[];
  total: number;
}

/**
 * One tool as the provider was told about it.
 *
 * The description is the half that decides behaviour and the half readable
 * nowhere else in the product: an agent that never calls a tool it has is
 * usually an agent whose tool describes itself badly.
 */
export interface ManifestTool {
  name: string;
  description: string | null;
  parameters_json_schema: Record<string, unknown>;
  /** `function`, or `output` for the tool carrying a structured answer. */
  kind: string;
}

/** One model request the run made, and what it cost in time. */
export interface ManifestRequest {
  index: number;
  started_at: string | null;
  duration_ms: number;
  model: string | null;
  /** How much history it carried - the size a long run is really paying for. */
  message_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  /** What the model asked to call next. Empty on the request that answered. */
  tool_calls: string[];
  finish_reason: string | null;
  /** The exception class, where the request raised - never its message. */
  failed: string | null;
}

/**
 * What a run handed its model, as `GET /runs/{run_id}/manifest` answers it.
 *
 * Recorded from the wire as the run happened rather than reconstructed from the
 * spec afterwards: the prompt the model saw is the spec's text plus the
 * platform's plus a binding's plus the bound skills', and the tool list is the
 * registry plus the organization's MCP servers minus whatever tool search hid.
 *
 * A run that never reached a model has none, and the endpoint answers 404 -
 * which is why the surface reading this must tell that from a failed request.
 */
export interface RunManifest {
  run_id: string;
  recorded_at: string;
  instructions: string | null;
  system_prompts: string[];
  tools: ManifestTool[];
  settings: Record<string, unknown>;
  requests: ManifestRequest[];
  /** The last request's messages, dumped - what the model saw at the end. */
  messages: Record<string, unknown>[];
  /** Whether the record was trimmed to fit its size ceiling. */
  truncated: boolean;
}

export interface ToolApproval {
  id: string;
  run_id: string;
  /** Whose *run* this is - the agent the queue is scoped by, never who is acting. */
  agent_id: string;
  /**
   * Whose run this is, as something readable.
   *
   * Optional because a decision returns the approval itself rather than the queue's
   * projection of it, and that response carries no joined names.
   */
  agent_name?: string | null;
  tool_id: string;
  /** Shown in full: approving a tool name without its arguments is a rubber stamp. */
  tool_args: Record<string, unknown>;
  /**
   * Who started the run this call belongs to.
   *
   * Not on the approval itself - an approval belongs to a run and a run belongs to a
   * person. Null for a run nobody started as themselves: an embedded widget's visitor
   * is anonymous.
   */
  triggered_by_user_id?: string | null;
  triggered_by_email?: string | null;
  /** Who decided, for the record view. A bare UUID is not an accountability trail. */
  decided_by_email?: string | null;
  /**
   * Which delegate is asking, when the call came from inside a delegation.
   *
   * Null means the run's own agent asked directly. A delegate's gated tool reaches
   * the parent's approval channel, so without this the row says `send_email` and
   * not who is sending it - and a queue of tool names with no actor is one people
   * approve blind.
   */
  subagent_name: string | null;
  /**
   * That delegate's own agent, for a link to it.
   *
   * Null for an inline specialist, which is defined inside its parent's spec and has
   * no agent of its own. So a name with no id is not a published agent, and must not
   * be shown as one.
   */
  subagent_agent_id: string | null;
  status: "pending" | "approved" | "rejected" | "expired";
  decided_by_user_id: string | null;
  decided_at: string | null;
  /**
   * How it was decided, which is a different question from what was decided.
   * `click` is somebody reading the arguments and pressing a button; `standing`
   * is a conversation that had waived approvals in advance, by the account
   * `decided_by_user_id` names. Both are `approved` (#925).
   */
  decided_via: "click" | "standing";
  note: string | null;
  created_at?: string;
}

export interface ApprovalList {
  items: ToolApproval[];
  total: number;
}

/**
 * One agent's line on the Spend tab.
 *
 * Two cost figures with two different names, which is the rule this row follows:
 * a number needing a different denominator needs a different word, never the same
 * word with different arithmetic. `cost_usd` is this agent's share of the window
 * with top-level runs only, so the column sums to the total printed above it;
 * `month_to_date_usd` is its own calendar month with delegated runs *included*,
 * because that is the spend its cap is a cap on.
 */
export interface CostByAgent {
  agent_id: string;
  /** The agent's name. Null only on the usage email's rows, which group by model. */
  agent_name: string | null;
  /** The model, on the usage email's per-model rows only. Null on the Spend tab. */
  model_label: string | null;
  cost_usd: string;
  run_count: number;
  /** How many of those runs had a model with no price: the cost is a floor by that much. */
  partial_run_count: number;
  /** Delegated runs included, and always the calendar month whatever window the tab shows. */
  month_to_date_usd: string | null;
  /** The cap in the published spec, or null for an agent that sets none. */
  monthly_cap_usd: string | null;
}

/** One model provider's share of the bill. */
export interface CostByProvider {
  /** Null for runs recorded before this was tracked - shown as such, never folded in. */
  provider: string | null;
  cost_usd: string;
  run_count: number;
}

/** One stored key's share. `label` is null once the key has been deleted. */
export interface CostByKey {
  /** The vault secret spend was attributed to; null once it has been deleted. */
  secret_id: string | null;
  label: string | null;
  cost_usd: string;
  run_count: number;
}

export interface CostSummary {
  /**
   * How many days the rolling window covered, or null once `from`/`to` made it
   * explicit.
   *
   * Nullable because `GET /spend` answers `None` whenever `from` was given: a
   * range and a count of days are two answers to one question, and the route
   * sends only the one that was asked for. Typed as `number` it read as always
   * present, so a caption built from it would render the default over a range
   * that is nothing like it - and nothing would have pointed at the line.
   */
  period_days: number | null;
  /** Where the window starts, however it was chosen - `from`, or `days` ago. */
  from_date: string;
  /** Where it ends, or null for "up to now". */
  to_date: string | null;
  /** Calendar-aligned, so it can be reconciled against an invoice. */
  month_to_date_usd: string;
  /**
   * How many of the window's runs ran on a model with no price. The breakdowns
   * are a floor by exactly this many, and the Spend tab says so once at the top.
   */
  partial_run_count: number;
  by_agent: CostByAgent[];
  /** What each vendor was paid - the question an invoice arrives with. */
  by_provider: CostByProvider[];
  /** Which key it went through, which is how a leaked or misused one is found. */
  by_key: CostByKey[];
}

/**
 * What `POST /runs/{id}/resume` answers with.
 *
 * The continuation itself, not an acknowledgement: resuming *executes* the agent,
 * so `output` is what it said after the approval - and it comes back over HTTP to
 * whoever asked, never over the conversation's WebSocket. A caller that discards
 * this leaves the reply nowhere, which is what made an approval look like it had
 * done nothing until the page was reloaded.
 */
/** A tool call a resumed run is now waiting on. */
export interface ParkedCall {
  id: string;
  tool_call_id: string | null;
  tool_name: string;
  tool_args: Record<string, unknown>;
}

/** One tool call an execution of a run made, and what came back from it. */
export interface RunStep {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  /** Null on the call the run has parked on - it has not run yet. */
  result: string | null;
}

/** What a call the run had already made finally returned. */
export interface SettledCall {
  tool_call_id: string;
  result: string;
}

export interface ResumedRun {
  run_id: string;
  output: string;
  status: RunStatus;
  /**
   * What the continuation called, in order.
   *
   * The only account of it there is. A resume executes the agent inside the HTTP
   * request rather than on the socket this conversation streams, so no `tool_call`
   * frame arrives for any of it - and a client drawing only `output` showed the
   * approved call finishing and nothing after it. Approving a command appeared to
   * do nothing, and the next approval request arrived for a step that had never
   * been drawn.
   */
  steps?: RunStep[];
  /**
   * What the run is waiting on *now*, empty unless it parked again.
   *
   * A resume runs the agent, and the agent can reach a second gated call. The
   * continuation runs over HTTP rather than this conversation's socket, so no
   * `tool_approval_required` frame arrives for it - this is the only place the new
   * calls can come from, and without it the panel closed on a run that was still
   * blocked and could no longer be decided from here.
   */
  /**
   * What the calls this execution inherited returned - on a resume, the very call
   * somebody approved.
   *
   * Not in `steps`: it was made by the execution that parked, so the caller has
   * already drawn its step and this updates it. Drawing it again would put the
   * same command in the turn twice.
   */
  settled?: SettledCall[];
  parked?: ParkedCall[];
  /** Serialised Decimal - never parse into a float for arithmetic. */
  cost_usd: string;
  /**
   * Whether `cost_usd` is a floor rather than the whole of it.
   *
   * A resumed turn draws its cost from here, so without it a continuation would
   * report an exact-looking figure where the parked half reported a caveat.
   */
  cost_is_partial: boolean;
  input_tokens: number;
  output_tokens: number;
}
