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
  /** The line of the edit the finding is about, as the edit has it; empty for none. */
  edit?: string;
  /** Why the line it named was cleared - it is not part of the edit. */
  edit_refused?: Rejection;
  /** `quote` is absent for a reader without `runs:view`. */
  evidence: { run_id: string; quote?: string }[];
  evidence_dropped: number;
}

export interface AuthoringRequest {
  id: string;
  kind: AuthoringKind;
  target: "agent" | "skill" | "context";
  agent_id: string | null;
  skill_id: string | null;
  context_id?: string | null;
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
    proposed?: number;
    recorded?: number;
    /** How many proposed changes nothing recorded, by why. */
    dropped?: Partial<Record<Rejection, number>>;
    /** The first of them, in the model's words without the quotes they cite. */
    rejected?: RejectedChange[];
    rejected_more?: number;
  } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** Why a change the assistant proposed was not recorded - the server's own names. */
export type Rejection =
  | "unanchored"
  | "ambiguous_anchor"
  | "no_change"
  | "unknown_tool"
  | "invalid_tool_change"
  | "not_a_target"
  | "operation"
  | "loosens_approval"
  | "weakens_protection"
  | "unknown_capability"
  | "invalid_config"
  | "does_not_apply"
  | "not_grantable"
  | "dismissed_before"
  | "unsupported"
  | "edit_not_in_diff"
  | "superseded";

export interface RejectedChange {
  kind: "instructions" | "tool_override" | "spec_field" | "finding";
  reason: Rejection;
  /**
   * The change as proposed: passages, a tool's new text, a field's path and value,
   * or a verify finding's verdict, text and the line it named.
   */
  change: {
    old_text?: string;
    new_text?: string;
    after?: string;
    capability_id?: string;
    tool_id?: string;
    name?: string | null;
    description?: string | null;
    path?: string;
    op?: string;
    value?: FieldValue;
    rationale?: string;
    verdict?: VerifyFinding["verdict"];
    text?: string;
    edit?: string;
  };
}

export interface EvidenceItem {
  run_id: string;
  /** Absent for a reader without `runs:view`. */
  quote: string | null;
}

/** A JSON value a field change reads or writes. */
export type FieldValue =
  string | number | boolean | null | FieldValue[] | { [key: string]: FieldValue };

/** What a field change is expected to do, measured on recent runs. */
export interface FieldEffect {
  /** For a change of model: what one recent run would cost on each, as decimals. */
  runs?: number;
  rough?: boolean;
  cost_per_run_before?: string | null;
  cost_per_run_after?: string | null;
  /** Tools the change makes reachable that write; an eval holds them back. */
  writes?: string[];
}

export interface Hunk {
  id: string;
  kind: "instructions" | "tool_override" | "spec_field";
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
  /** A field change: its path in the spec, and what it does there. */
  path: string | null;
  op: "set" | "add" | "remove" | null;
  base_value: FieldValue;
  new_value: FieldValue;
  accepted_value: FieldValue;
  effect: FieldEffect | null;
  /** Names of the models, collections, context files and servers it refers to. */
  names: Record<string, string>;
  /** Why Accept is refused for now: `check_first`, `inconclusive`, `regression` or `crashed`. */
  blocked: "check_first" | "inconclusive" | "regression" | "crashed" | null;
  expected_effect: string;
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
  /** A field change's value, edited before accepting. */
  value?: FieldValue;
}

/** A check names a dataset, or an eval suite whose dataset and environment it runs. */
export interface ProposalCheck {
  dataset_id?: string;
  suite_id?: string;
  dataset_version?: number;
  environment_id?: string;
  agent_id?: string;
  proposal_id?: string;
}

export interface AuthoringWaiting {
  agents: {
    agent_id: string;
    name: string;
    instructions: number;
    tools: number;
    fields?: number;
  }[];
  skills: number;
  contexts?: number;
}

/** A context file change the assistant proposed, beside the file as it stands. */
export interface ContextChange {
  id: string;
  context_id: string;
  context_name: string;
  description: string | null;
  content: string;
  current_description: string | null;
  current_content: string;
  status: "pending" | "applied" | "discarded";
  decided_by_user_id: string | null;
  decided_at: string | null;
  /** The file changed since the proposal was written; Apply refuses it. */
  stale: boolean;
  rationale: string;
  evidence: EvidenceItem[];
  evidence_dropped: number;
  expected_effect: string;
  authoring_request_id: string | null;
  /** The agents that read the file, as far as the reader may see them. */
  used_by: { id: string; name: string }[];
  created_at: string;
  updated_at: string | null;
}

export interface ContextChangeList {
  items: ContextChange[];
  total: number;
}
