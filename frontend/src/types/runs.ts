/** Types for run history, approvals and the cost dashboard. */

export type RunStatus =
  "running" | "completed" | "failed" | "cancelled" | "awaiting_approval" | "budget_exceeded";

export interface AgentRun {
  id: string;
  agent_id: string;
  agent_version_id: string | null;
  user_id: string | null;
  surface: string;
  status: RunStatus;
  model_label: string | null;
  input_tokens: number;
  output_tokens: number;
  /** Serialised Decimal - never parse into a float for arithmetic. */
  cost_usd: string;
  /** True when a model in this run had no price; the cost is a floor. */
  cost_is_partial: boolean;
  logfire_trace_id: string | null;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface AgentRunList {
  items: AgentRun[];
  total: number;
}

export interface ToolApproval {
  id: string;
  run_id: string;
  agent_id: string;
  tool_id: string;
  /** Shown in full: approving a tool name without its arguments is a rubber stamp. */
  tool_args: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired";
  decided_by_user_id: string | null;
  decided_at: string | null;
  note: string | null;
  created_at?: string;
}

export interface ApprovalList {
  items: ToolApproval[];
  total: number;
}

export interface CostByAgent {
  agent_id: string;
  model_label: string | null;
  cost_usd: string;
  run_count: number;
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
  period_days: number;
  /** Calendar-aligned, so it can be reconciled against an invoice. */
  month_to_date_usd: string;
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
export interface ResumedRun {
  run_id: string;
  output: string;
  status: RunStatus;
  /** Serialised Decimal - never parse into a float for arithmetic. */
  cost_usd: string;
  input_tokens: number;
  output_tokens: number;
}
