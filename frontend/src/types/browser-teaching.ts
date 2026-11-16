export type TeachingStatus =
  "recording" | "paused" | "review" | "proposed" | "discarded" | "expired";
export type TeachingGeneration =
  "none" | "queued" | "generating" | "succeeded" | "refused" | "unknown" | "cancelled";
export type TeachingSource = "manual" | "refinement";
export type TeachingAction =
  "navigate" | "click" | "select" | "input_parameter" | "scroll" | "checkpoint";
export type TeachingRole =
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
export const TEACHING_REASONS = [
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
export type TeachingReason = (typeof TEACHING_REASONS)[number];

/** The server deliberately sends no typed text, full URL, DOM label or selector. */
export interface TeachingEvent {
  sequence: number;
  input_id: string;
  action: TeachingAction;
  origin: string;
  target: { role: TeachingRole; fingerprint: string } | null;
  direction: "up" | "down" | null;
  human_step: boolean;
}
export interface TeachingParameter {
  name: string;
  description: string;
}
export interface TeachingReviewedAction {
  sequence: number;
  label: string;
  parameter: string | null;
  path_template: string | null;
  omit: boolean;
}
export interface TeachingReview {
  name: string;
  description: string;
  actions: TeachingReviewedAction[];
  parameters: TeachingParameter[];
  prerequisites: string[];
  success_checks: string[];
}
export interface BrowserProcedure {
  schema_version: 1;
  origins: string[];
  steps: {
    action: TeachingAction;
    origin: string;
    label: string;
    role: TeachingRole | null;
    parameter: string | null;
    path_template: string | null;
    direction: "up" | "down" | null;
    human_step: boolean;
  }[];
  parameters: TeachingParameter[];
  prerequisites: string[];
  success_checks: string[];
  source_session_id: string;
  source_hash: string;
  source: TeachingSource;
  verified_success: boolean;
}
export interface BrowserTeaching {
  id: string;
  agent_id: string;
  run_id: string;
  call_id: string;
  tab_id: string;
  target_skill_id: string | null;
  title: string;
  allowed_origins: string[];
  source: TeachingSource;
  verified_success: boolean;
  status: TeachingStatus;
  revision: number;
  reason_code: TeachingReason | null;
  events: TeachingEvent[];
  review: TeachingReview | null;
  procedure: BrowserProcedure | null;
  generation_state: TeachingGeneration;
  generation_mode: "reviewed" | "assistant" | null;
  max_cost_usd: string | null;
  proposal_id: string | null;
  created_at: string;
  expires_at: string;
  capture_ends_at: string;
}
export interface TeachingStart {
  request_id: string;
  run_id: string;
  call_id: string;
  tab_id: string;
  takeover_id: string;
  title: string;
  allowed_origins: string[];
}
export type TeachingChange =
  | { action: "pause" }
  | { action: "resume"; takeover_id: string }
  | { action: "review"; review: TeachingReview };
export type TeachingPropose = { mode: "reviewed" } | { mode: "assistant"; max_cost_usd: string };
export interface TeachingPolicy {
  enabled: boolean;
  generation: string | null;
  deployment_enabled: boolean;
}
export interface TeachingPreference {
  agent_id: string;
  enabled: boolean;
  generation: string | null;
  allowed: boolean;
}
export interface TeachingToggle {
  generation: string | null;
  enabled: boolean;
}
export type TeachingSummary = Pick<
  BrowserTeaching,
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
export interface TeachingList {
  items: TeachingSummary[];
  next_cursor: string | null;
}
