/**
 * Eval runs - an agent answering every case of a dataset version, and how the
 * result compares with a baseline.
 *
 * Mirrors `app/schemas/eval_run.py`. Money arrives as decimal strings.
 */

import type { DatasetCaseContent } from "./datasets";
import type { EvalSuiteResultStatus, EvalSuiteTrigger, ThresholdReason } from "./eval-suites";
import type { CaseScore } from "./scoring";

export type EvalRunStatus =
  "queued" | "running" | "completed" | "cancelled" | "failed" | "budget_exceeded";
export type EvalRunPurpose = "manual" | "gate";
export type ArmRole = "candidate" | "baseline";
export type ArmSource = "version" | "draft" | "explicit";
export type AttemptStatus = "pending" | "running" | "done" | "failed" | "skipped";
export type CallOutcome = "executed" | "blocked" | "replayed" | "divergent";
export type Flip = "regression" | "fixed" | "unchanged" | "incomplete";
/**
 * How one attempt came out: `failed` includes a run the agent crashed;
 * `incomplete` is one the provider or a scorer failed on, or that never ran;
 * `ungraded` is an answer nothing grades.
 */
export type CaseState = "passed" | "failed" | "incomplete" | "ungraded";
export type Verdict = "better" | "worse" | "mixed" | "no_difference" | "invalid";
/** Which way the candidate moved as a whole, when the confirmed flips can tell. */
export type Overall = "better" | "worse";
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
  /** The model the judge would grade on; null when no judge grades the run. */
  judge_model_profile_id: string | null;
  total_usd: string;
  rerun_ceiling_usd: string;
  agent_remaining_usd: string | null;
  org_remaining_usd: string | null;
  agent_after_usd: string | null;
  org_after_usd: string | null;
  affordable: boolean;
  /** Cases nothing in the dataset's scoring would grade; any makes the result inconclusive. */
  ungraded_cases: number;
  /** The version this run would be measured against, when no comparable earlier run of it exists. */
  missing_baseline_version: number | null;
}

/** Both axes for one arm: quality as each case settled on its attempts, efficiency over first ones. */
export interface ArmSummary {
  cases: number;
  passed: number;
  /** A case the agent crashed on included. */
  failed: number;
  /** Undecided because the provider, a scorer or the run failed on them, or their tries tied. */
  incomplete: number;
  /** Undecided because nothing in the scoring grades them. */
  ungraded: number;
  /** First answers the agent's run failed before giving; each fails a suite even when its reruns pass. */
  crashed: number;
  /** Each case settled by the majority of its attempts - its first alone when it was not rerun. */
  pass_rate: number | null;
  /** The first attempts alone, reruns aside. */
  first_pass_rate: number | null;
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
  /** A fingerprint of the spec this side ran. */
  spec_hash: string;
  /** The skills this side served a proposed body for instead of the stored one. */
  skill_ids?: string[];
  /** The context files this side served a proposed body for instead of the stored one. */
  context_ids?: string[];
  summary: ArmSummary;
  by_tag: Record<string, ArmSummary>;
  /** The cases this side's first answer was not graded on, by a scorer that reached no verdict. */
  ungraded_cases: { case_id: string; input: string }[];
  /** This side's failed first answers not yet waiting for review. */
  unsent_failed: number;
  /** The error every first answer of this side failed with, when they all failed with one. */
  failed_alike: string | null;
}

/**
 * How a finished run's first candidate came out against its baseline. A null
 * `verdict` and `baseline` make it the first result later versions are
 * measured against.
 */
export interface EvalOutcome {
  candidate_arm_id: string;
  verdict: Verdict | null;
  overall: Overall | null;
  baseline: ComparisonSide | null;
  regressions_confirmed: number;
  fixed_confirmed: number;
  candidate_pass_rate: number | null;
  baseline_pass_rate: number | null;
  candidate_first_pass_rate: number | null;
  baseline_first_pass_rate: number | null;
  /** The candidate's cases neither passed nor failed. */
  candidate_undecided: number;
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
  /** How many of its scores the run sent to review itself - confirmed regressions and ungraded answers. */
  routed_to_review: number;
  /** How many older scores of the same cases, still waiting, the run's own sending replaced. */
  routed_replacing: number;
  /** The model the judge graded this run on; null when none did. */
  judge_model_profile_id: string | null;
  /** Why the run could not send its scores to review itself; null when it could. */
  routing_error: { code: string; message: string } | null;
  /** This run's scores no scorer reached a verdict on and no person decided. */
  ungraded_score_ids: string[];
  /** Cases left out because they come from the evidence of the proposal being checked. */
  excluded_case_ids?: string[];
  /** The eval suite that started this run; null for one started by hand. */
  suite?: { id: string; name: string; trigger: EvalSuiteTrigger } | null;
  /** On the single-run read of a run of the draft: whether the draft changed since. */
  draft_changed?: boolean | null;
  /** On the single-run read of a check made on an eval suite: what the suite would say. */
  suite_check?: EvalSuiteCheck | null;
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
  state: CaseState;
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
  /** The question the case asks. */
  input: string;
  flip: Flip;
  confirmed: boolean;
  baseline: boolean | null;
  candidate: boolean | null;
  baseline_reruns: (boolean | null)[];
  candidate_reruns: (boolean | null)[];
  tags: string[];
  /** Why the candidate's first answer failed, when its run crashed rather than answered. */
  candidate_error: string | null;
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
  overall: Overall | null;
  p_value: number | null;
  invalid_reason: string | null;
  regressions_confirmed: number;
  regressions_unconfirmed: number;
  fixed_confirmed: number;
  fixed_unconfirmed: number;
  compared: number;
  not_compared: number;
  /** Cases both sides answered whose input or expectations changed between them. */
  changed: number;
  /** Whether the baseline was asked the flipped cases again; false leaves every flip unconfirmed. */
  baseline_rerun: boolean;
  candidate_summary: ArmSummary;
  baseline_summary: ArmSummary | null;
  efficiency: Efficiency | null;
  cases: CaseFlip[];
  flips_by_tag: Record<string, Partial<Record<Flip, number>>>;
}

/**
 * What the eval suite a check of suggestions ran on would have said of the run, by
 * the threshold it had when the check started. The check is none of the suite's runs.
 */
export interface EvalSuiteCheck {
  suite_id: string;
  /** The suite's name when the check started. */
  name: string;
  /** Whether the suite is still there, under this agent, to be opened. */
  suite_exists: boolean;
  /** Null while the run runs, or when it ended without completing. */
  status: Extract<EvalSuiteResultStatus, "passed" | "failed" | "inconclusive"> | null;
  reasons: ThresholdReason[];
}
