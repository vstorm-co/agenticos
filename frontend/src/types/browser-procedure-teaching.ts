export type BrowserProcedureTeachingStatus =
  "recording" | "paused" | "review" | "proposed" | "discarded" | "expired";
export type BrowserProcedureTeachingGeneration =
  "none" | "queued" | "generating" | "succeeded" | "refused" | "unknown" | "cancelled";
export type BrowserProcedureTeachingSource = "manual" | "refinement";
export type BrowserProcedureTeachingAction =
  "navigate" | "click" | "select" | "input_parameter" | "scroll" | "checkpoint";
export type BrowserProcedureTeachingRole =
  | "button"
  | "link"
  | "textbox"
  | "combobox"
  | "checkbox"
  | "radio"
  | "tab"
  | "menuitem"
  | "option"
  | "switch";
export const BROWSER_PROCEDURE_TEACHING_REASONS = [
  "teaching_disabled",
  "teaching_unavailable",
  "browser_ownership_lost",
  "credential_output_protected",
  "authority_changed",
  "teaching_expired",
  "event_limit_reached",
  "event_bytes_limit_reached",
  "capture_time_limit_reached",
  "human_authentication_required",
  "human_step_required",
  "origin_not_allowed",
  "capture_unavailable",
  "paused_by_owner",
  "stale_revision",
  "event_sequence_conflict",
  "review_required",
  "generation_budget_refused",
  "draft_not_usable",
  "generation_failed",
  "generation_outcome_unknown",
  "learning_opted_out",
  "task_not_completed",
] as const;
export type BrowserProcedureTeachingReason = (typeof BROWSER_PROCEDURE_TEACHING_REASONS)[number];

/** The server deliberately sends no typed text, full URL, DOM label or selector. */
export interface BrowserProcedureTeachingEvent {
  sequence: number;
  input_id: string;
  action: BrowserProcedureTeachingAction;
  origin: string;
  target: { role: BrowserProcedureTeachingRole; fingerprint: string } | null;
  direction: "up" | "down" | null;
  human_step: boolean;
}
export interface BrowserProcedureTeachingParameter {
  name: string;
  description: string;
}
export interface BrowserProcedureTeachingReviewedAction {
  sequence: number;
  label: string;
  parameter: string | null;
  path_template: string | null;
  omit: boolean;
}
export interface BrowserProcedureTeachingReview {
  name: string;
  description: string;
  actions: BrowserProcedureTeachingReviewedAction[];
  parameters: BrowserProcedureTeachingParameter[];
  prerequisites: string[];
  success_checks: string[];
}
export interface BrowserProcedure {
  schema_version: 1;
  origins: string[];
  steps: {
    action: BrowserProcedureTeachingAction;
    origin: string;
    label: string;
    role: BrowserProcedureTeachingRole | null;
    parameter: string | null;
    path_template: string | null;
    direction: "up" | "down" | null;
    human_step: boolean;
  }[];
  parameters: BrowserProcedureTeachingParameter[];
  prerequisites: string[];
  success_checks: string[];
  source_session_id: string;
  source_hash: string;
  source: BrowserProcedureTeachingSource;
  verified_success: boolean;
}
export interface BrowserProcedureTeaching {
  id: string;
  agent_id: string;
  run_id: string;
  call_id: string;
  tab_id: string;
  target_skill_id: string | null;
  title: string;
  allowed_origins: string[];
  source: BrowserProcedureTeachingSource;
  verified_success: boolean;
  status: BrowserProcedureTeachingStatus;
  revision: number;
  reason_code: BrowserProcedureTeachingReason | null;
  events: BrowserProcedureTeachingEvent[];
  review: BrowserProcedureTeachingReview | null;
  procedure: BrowserProcedure | null;
  generation_state: BrowserProcedureTeachingGeneration;
  generation_mode: "reviewed" | "assistant" | null;
  max_cost_usd: string | null;
  proposal_id: string | null;
  created_at: string;
  expires_at: string;
  capture_ends_at: string;
}
export interface BrowserProcedureTeachingStart {
  request_id: string;
  run_id: string;
  call_id: string;
  tab_id: string;
  takeover_id: string;
  title: string;
  allowed_origins: string[];
}
export type BrowserProcedureTeachingChange =
  | { action: "pause" }
  | { action: "resume"; takeover_id: string }
  | { action: "review"; review: BrowserProcedureTeachingReview };
export type BrowserProcedureTeachingPropose =
  { mode: "reviewed" } | { mode: "assistant"; max_cost_usd: string };
export interface BrowserProcedureTeachingPolicy {
  enabled: boolean;
  generation: string | null;
  deployment_enabled: boolean;
}
export interface BrowserProcedureTeachingPreference {
  agent_id: string;
  enabled: boolean;
  generation: string | null;
  allowed: boolean;
}
export interface BrowserProcedureTeachingToggle {
  generation: string | null;
  enabled: boolean;
}
export type BrowserProcedureTeachingSummary = Pick<
  BrowserProcedureTeaching,
  | "id"
  | "agent_id"
  | "target_skill_id"
  | "title"
  | "allowed_origins"
  | "source"
  | "verified_success"
  | "status"
  | "revision"
  | "reason_code"
  | "generation_state"
  | "proposal_id"
  | "created_at"
  | "expires_at"
  | "capture_ends_at"
>;
export interface BrowserProcedureTeachingList {
  items: BrowserProcedureTeachingSummary[];
  next_cursor: string | null;
}
