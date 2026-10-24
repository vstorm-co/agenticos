import type { EvalSuite, EvalSuiteResult, EvalSuiteSummary } from "@/types/eval-suites";

/** A summary of a run that passed every case. */
export function suiteSummary(overrides: Partial<EvalSuiteSummary> = {}): EvalSuiteSummary {
  return {
    pass_rate: 1,
    first_pass_rate: 1,
    cases: 4,
    baseline_pass_rate: null,
    baseline_run_id: null,
    baseline_version: null,
    paired: false,
    verdict: null,
    overall: null,
    invalid_reason: null,
    regressions_confirmed: 0,
    regressions_unconfirmed: 0,
    fixed_confirmed: 0,
    cost_per_pass_usd: "0.01",
    baseline_cost_per_pass_usd: null,
    p95_ms: 900,
    baseline_p95_ms: null,
    reasons: [],
    failing_cases: [],
    message: null,
    ...overrides,
  };
}

/** A scheduled result that passed on version 3. */
export function suiteResult(overrides: Partial<EvalSuiteResult> = {}): EvalSuiteResult {
  return {
    id: "result-1",
    suite_id: "suite-1",
    trigger: "schedule",
    trigger_detail: null,
    version_number: 3,
    baseline_version_number: null,
    environment_id: null,
    status: "passed",
    reason: null,
    due_at: "2026-10-19T06:00:00Z",
    eval_run_id: "run-1",
    baseline_eval_run_id: null,
    run_as_user_id: "user-1",
    threshold: {
      min_pass_rate: null,
      max_confirmed_regressions: 0,
      max_cost_per_pass_rise: null,
      max_p95_rise: null,
    },
    summary: suiteSummary(),
    notified_at: null,
    created_at: "2026-10-19T06:00:00Z",
    started_at: "2026-10-19T06:00:05Z",
    settled_at: "2026-10-19T06:03:00Z",
    ...overrides,
  };
}

/** A running suite on agent `agent-1`, checked nightly in Warsaw and on every publish. */
export function evalSuite(overrides: Partial<EvalSuite> = {}): EvalSuite {
  return {
    id: "suite-1",
    agent_id: "agent-1",
    agent_name: "Clerk",
    dataset_id: "dataset-1",
    dataset_name: "refunds",
    environment_id: null,
    environment_name: null,
    owner_user_id: "user-1",
    owner_email: "owner@example.com",
    name: "Nightly",
    description: null,
    is_active: true,
    paused_reason: null,
    threshold: {
      min_pass_rate: null,
      max_confirmed_regressions: 0,
      max_cost_per_pass_rise: null,
      max_p95_rise: null,
    },
    on_publish: true,
    on_promotion: false,
    on_dependency_change: false,
    schedule: { cron: "0 6 * * *", timezone: "Europe/Warsaw" },
    next_fire_at: "2026-10-20T04:00:00Z",
    max_run_usd: null,
    pin: null,
    dataset_has_cases: true,
    last_result: suiteResult(),
    open_result: null,
    created_at: "2026-10-18T10:00:00Z",
    updated_at: null,
    ...overrides,
  };
}
