/**
 * Eval suites - a dataset an agent is held to, run on a schedule and on the
 * changes that matter, and each time it ran.
 *
 * Mirrors `app/schemas/eval_suite.py`. Money arrives as decimal strings.
 */

import type { EvalRunEstimate, Overall, Verdict } from "./eval-runs";

export type EvalSuiteTrigger =
  "schedule" | "publish" | "promotion" | "dependency" | "manual" | "gate";
export type EvalSuiteResultStatus =
  "pending" | "running" | "passed" | "failed" | "inconclusive" | "skipped" | "error";
export type ThresholdReasonCode =
  | "pass_rate_below"
  | "nothing_graded"
  | "regressions"
  | "cost_per_pass_rise"
  | "p95_rise"
  | "invalid_comparison"
  | "ungraded";

/** What a result must meet. Fractions: 0.8 is eighty per cent. */
export interface EvalSuiteThreshold {
  min_pass_rate: number | null;
  max_confirmed_regressions: number;
  max_cost_per_pass_rise: number | null;
  max_p95_rise: number | null;
}

/** A cron expression read on the wall clock of an IANA time zone. */
export interface EvalSuiteSchedule {
  cron: string;
  timezone: string;
}

export interface ThresholdReason {
  code: ThresholdReasonCode;
  value: number | null;
  limit: number | null;
  detail: string | null;
}

export interface FailingCase {
  case_id: string;
  input: string;
  kind: "regression" | "failed" | "ungraded";
}

export interface EvalSuiteSummary {
  pass_rate: number | null;
  first_pass_rate: number | null;
  cases: number;
  baseline_pass_rate: number | null;
  baseline_run_id: string | null;
  baseline_version: number | null;
  paired: boolean;
  verdict: Verdict | null;
  overall: Overall | null;
  invalid_reason: string | null;
  regressions_confirmed: number;
  regressions_unconfirmed: number;
  fixed_confirmed: number;
  cost_per_pass_usd: string | null;
  baseline_cost_per_pass_usd: string | null;
  p95_ms: number | null;
  baseline_p95_ms: number | null;
  reasons: ThresholdReason[];
  failing_cases: FailingCase[];
  /** Why a result was skipped or ended without a verdict. */
  message: string | null;
}

export interface EvalSuiteResult {
  id: string;
  suite_id: string;
  trigger: EvalSuiteTrigger;
  trigger_detail: Record<string, string> | null;
  version_number: number | null;
  baseline_version_number: number | null;
  environment_id: string | null;
  status: EvalSuiteResultStatus;
  /** Anything but a pass: what tells the owner, and what makes a suite failing. */
  alerting: boolean;
  /** A code the console words: `budget`, `over_cost_cap`, `ai_assistance_off`... */
  reason: string | null;
  due_at: string;
  eval_run_id: string | null;
  baseline_eval_run_id: string | null;
  run_as_user_id: string | null;
  threshold: EvalSuiteThreshold;
  summary: EvalSuiteSummary | null;
  notified_at: string | null;
  created_at: string;
  started_at: string | null;
  settled_at: string | null;
}

export interface EvalSuiteResultList {
  items: EvalSuiteResult[];
  total: number;
}

export interface EvalSuite {
  id: string;
  agent_id: string;
  agent_name: string;
  dataset_id: string;
  /** Null when the reader cannot see the dataset, which still runs. */
  dataset_name: string | null;
  environment_id: string | null;
  environment_name: string | null;
  owner_user_id: string | null;
  owner_email: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  /** Why the platform paused it: `owner_inactive` or `owner_lacks_access`. */
  paused_reason: string | null;
  threshold: EvalSuiteThreshold;
  on_publish: boolean;
  on_promotion: boolean;
  on_dependency_change: boolean;
  schedule: EvalSuiteSchedule | null;
  next_fire_at: string | null;
  max_run_usd: string | null;
  last_result: EvalSuiteResult | null;
  /** The result running now, or waiting to start. */
  open_result: EvalSuiteResult | null;
  created_at: string;
  updated_at: string | null;
}

export interface EvalSuiteList {
  items: EvalSuite[];
  total: number;
}

/** A suite as the form saves it - the same body creates one and updates one. */
export interface EvalSuiteInput {
  name: string;
  description: string | null;
  dataset_id: string;
  environment_id: string | null;
  threshold: EvalSuiteThreshold;
  on_publish: boolean;
  on_promotion: boolean;
  on_dependency_change: boolean;
  schedule: EvalSuiteSchedule | null;
  max_run_usd: string | null;
}

export interface EvalSuiteEstimateRequest {
  dataset_id: string;
  environment_id: string | null;
  schedule: EvalSuiteSchedule | null;
}

/** One run alone, one beside the previous version, and a month of the schedule. */
export interface EvalSuiteEstimate {
  run: EvalRunEstimate;
  paired_run: EvalRunEstimate | null;
  fires_per_month: number | null;
  monthly_usd: string | null;
}
