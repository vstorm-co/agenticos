/** The authoring assistant: what it was asked, what it proposed, and the decisions on it. */

export type AuthoringKind = "improve" | "verify";
export type AuthoringStatus = "queued" | "running" | "completed" | "failed";
export type HunkStatus = "pending" | "accepted" | "dismissed";

export interface AuthoringStart {
  kind: AuthoringKind;
  window_days: number;
}

export interface AuthoringEstimate {
  runs: number;
  rated_down: number;
  calls: number;
  estimate_usd: string;
  affordable: boolean;
  /** `no_evidence` or `no_draft_change` when it cannot start. */
  reason: string | null;
}

export interface VerifyFinding {
  verdict: "supports" | "risk" | "removed";
  text: string;
  /** `quote` is absent for a reader without `runs:view`. */
  evidence: { run_id: string; quote?: string }[];
  evidence_dropped: number;
}

export interface AuthoringRequest {
  id: string;
  kind: AuthoringKind;
  target: "agent" | "skill";
  agent_id: string | null;
  skill_id: string | null;
  status: AuthoringStatus;
  error: string | null;
  estimate_usd: string;
  cost_usd: string;
  run_ids: string[];
  window_days: number;
  evidence: { runs?: number; rated_down?: number };
  report: {
    summary?: string;
    expected_effect?: string;
    findings?: VerifyFinding[];
  } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvidenceItem {
  run_id: string;
  /** Absent for a reader without `runs:view`. */
  quote: string | null;
}

export interface Hunk {
  id: string;
  kind: "instructions" | "tool_override";
  origin: AuthoringKind;
  status: HunkStatus;
  old_text: string;
  new_text: string;
  accepted_text: string | null;
  context_before: string;
  context_after: string;
  capability_id: string | null;
  tool_id: string | null;
  base_name: string | null;
  base_description: string | null;
  new_name: string | null;
  new_description: string | null;
  rationale: string;
  evidence: EvidenceItem[];
  evidence_dropped: number;
  /** Pending: still fits the draft. Accepted: Undo still can. */
  applies: boolean;
  decided_at: string | null;
}

export interface SuggestionBatch {
  id: string;
  agent_id: string;
  status: "open" | "superseded" | "published";
  expected_effect: string;
  request_id: string | null;
  hunks: Hunk[];
  check_eval_run_ids: string[];
  created_at: string;
}

export interface AgentAuthoring {
  batch: SuggestionBatch | null;
  latest: AuthoringRequest | null;
  verify: AuthoringRequest | null;
}

export interface HunkDecision {
  action: "accept" | "dismiss" | "undo";
  text?: string;
}

export interface ProposalCheck {
  dataset_id: string;
  dataset_version?: number;
  environment_id?: string;
  agent_id?: string;
  proposal_id?: string;
}

export interface AuthoringWaiting {
  agents: { agent_id: string; name: string; instructions: number; tools: number }[];
  skills: number;
}
