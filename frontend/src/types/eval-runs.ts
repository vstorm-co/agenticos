/**
 * Eval runs - an agent answering every case of a dataset version, and how the
 * result compares with a baseline.
 *
 * Mirrors `app/schemas/eval_run.py`. Money arrives as decimal strings.
 */

import type { DatasetCaseContent } from "./datasets";
import type { CaseScore } from "./scoring";

export type EvalRunStatus =
  "queued" | "running" | "completed" | "cancelled" | "failed" | "budget_exceeded";
export type EvalRunPurpose = "manual" | "gate";
export type ArmRole = "candidate" | "baseline";
export type ArmSource = "version" | "draft" | "explicit";
export type AttemptStatus = "pending" | "running" | "done" | "failed" | "skipped";
export type CallOutcome = "executed" | "blocked" | "replayed" | "divergent";
export type Flip = "regression" | "fixed" | "unchanged" | "incomplete";
export type Verdict = "better" | "worse" | "no_difference" | "inconclusive" | "invalid";
export type Trend = "better" | "worse" | "unchanged" | "unknown";
export type EstimateBasis = "history" | "fallback" | "cached";
export type CaseOutcomeFilter = "passed" | "failed" | "undecided";

/** What to run - the same body estimates and starts. */
export interface EvalRunRequest {
  dataset_id: string;
  dataset_version?: number | null;
  environment_id?: string | null;
  candidate: "version" | "draft";
  version?: number | null;
  model_profile_ids: string[];
  paired_baseline: boolean;
  baseline_version?: number | null;
  from_recordings: boolean;
  live_reads: boolean;
  reruns?: number | null;
}

export interface ArmEstimate {
  role: ArmRole;
  source: ArmSource;
  version_number: number | null;
  model_profile_id: string | null;
  model_label: string;
  cost_per_case_usd: string;
  cost_usd: string;
  basis: EstimateBasis;
  cached_from_run_id: string | null;
  cached_at: string | null;
}

/** The spend a run asks consent for, and what each budget keeps after it. */
export interface EvalRunEstimate {
  cases: number;
  arms: ArmEstimate[];
  judge_usd: string;
  total_usd: string;
  rerun_ceiling_usd: string;
  agent_remaining_usd: string | null;
  org_remaining_usd: string | null;
  agent_after_usd: string | null;
  org_after_usd: string | null;
  affordable: boolean;
}

/** Both axes for one arm over its first attempts. */
export interface ArmSummary {
  cases: number;
  passed: number;
  failed: number;
  incomplete: number;
  pass_rate: number | null;
  cost_usd: string;
  cost_per_pass_usd: string | null;
  avg_tokens: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface EvalRunArm {
  id: string;
  role: ArmRole;
  position: number;
  source: ArmSource;
  agent_version_id: string | null;
  version_number: number | null;
  model_profile_id: string | null;
  model_label: string;
  reused_from_arm_id: string | null;
  summary: ArmSummary;
  by_tag: Record<string, ArmSummary>;
}

/**
 * How a finished run's first candidate came out against its baseline. A null
 * `verdict` and `baseline` make it the first result later versions are
 * measured against.
 */
export interface EvalOutcome {
  candidate_arm_id: string;
  verdict: Verdict | null;
  baseline: ComparisonSide | null;
  regressions_confirmed: number;
  fixed_confirmed: number;
  candidate_pass_rate: number | null;
  baseline_pass_rate: number | null;
}

export interface EvalRun {
  id: string;
  agent_id: string;
  dataset_id: string;
  dataset_name: string;
  dataset_version: number;
  environment_id: string | null;
  status: EvalRunStatus;
  purpose: EvalRunPurpose;
  paired: boolean;
  from_recordings: boolean;
  live_reads: boolean;
  reruns: number;
  estimate_usd: string;
  /** What confirming reruns may add on top of the estimate. */
  rerun_ceiling_usd: string;
  cost_usd: string;
  cost_is_partial: boolean;
  attempts_done: number;
  attempts_total: number;
  /** The cases the run answers. */
  cases: number;
  /** First answers finished and in all, every side's; the rest are confirming reruns. */
  first_done: number;
  first_total: number;
  /** The verdict once the run has ended; null while it answers. */
  outcome: EvalOutcome | null;
  error: string | null;
  created_by_user_id: string | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  arms: EvalRunArm[];
}

export interface EvalRunList {
  items: EvalRun[];
  total: number;
}

export interface EvalCall {
  tool: string;
  args: Record<string, unknown>;
  outcome: CallOutcome;
  reason: string | null;
}

export interface EvalAttempt {
  id: string;
  arm_id: string;
  attempt: number;
  status: AttemptStatus;
  agent_run_id: string | null;
  answer: string | null;
  calls: EvalCall[];
  cost_usd: string | null;
  cost_is_partial: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  error: string | null;
  outcome: boolean | null;
  score: CaseScore | null;
}

export interface EvalCase {
  case_id: string;
  case_revision_id: string;
  position: number;
  input: string;
  tags: string[];
  /** What the case expects, as the revision the run answered holds it. */
  expectation: DatasetCaseContent | null;
  attempts: EvalAttempt[];
}

export interface EvalCaseList {
  items: EvalCase[];
  total: number;
}

export interface ComparisonSide {
  run_id: string;
  arm_id: string;
  role: ArmRole;
  source: ArmSource;
  version_number: number | null;
  model_label: string;
  dataset_version: number;
  finished_at: string | null;
}

export interface CaseFlip {
  case_id: string;
  flip: Flip;
  confirmed: boolean;
  baseline: boolean | null;
  candidate: boolean | null;
  baseline_reruns: (boolean | null)[];
  candidate_reruns: (boolean | null)[];
  tags: string[];
}

export interface Efficiency {
  cost_per_pass: Trend;
  avg_tokens: Trend;
  p50_ms: Trend;
  p95_ms: Trend;
}

/** A candidate arm against its baseline; `baseline` null means nothing to compare with yet. */
export interface EvalComparison {
  candidate: ComparisonSide;
  baseline: ComparisonSide | null;
  paired: boolean;
  verdict: Verdict | null;
  p_value: number | null;
  invalid_reason: string | null;
  regressions_confirmed: number;
  regressions_unconfirmed: number;
  fixed_confirmed: number;
  fixed_unconfirmed: number;
  compared: number;
  not_compared: number;
  candidate_summary: ArmSummary;
  baseline_summary: ArmSummary | null;
  efficiency: Efficiency | null;
  cases: CaseFlip[];
  flips_by_tag: Record<string, Partial<Record<Flip, number>>>;
}
