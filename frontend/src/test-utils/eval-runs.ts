/** Eval runs as the API answers them, for the tests of the console that reads them. */

import type {
  ArmEstimate,
  ArmSummary,
  CaseFlip,
  EvalAttempt,
  EvalCase,
  EvalComparison,
  EvalRun,
  EvalRunArm,
  EvalRunEstimate,
} from "@/types/eval-runs";

export const SUMMARY: ArmSummary = {
  cases: 4,
  passed: 3,
  failed: 1,
  incomplete: 0,
  pass_rate: 0.75,
  cost_usd: "0.040000",
  cost_per_pass_usd: "0.013333",
  avg_tokens: 120.4,
  p50_ms: 500,
  p95_ms: 1500,
};

export function arm(overrides: Partial<EvalRunArm> = {}): EvalRunArm {
  return {
    id: "arm-1",
    role: "candidate",
    position: 0,
    source: "version",
    agent_version_id: "v7",
    version_number: 7,
    model_profile_id: "m1",
    model_label: "gpt-4.1",
    reused_from_arm_id: null,
    summary: SUMMARY,
    by_tag: { refunds: SUMMARY },
    ...overrides,
  };
}

export function evalRun(overrides: Partial<EvalRun> = {}): EvalRun {
  return {
    id: "run-1",
    agent_id: "agent-1",
    dataset_id: "ds-1",
    dataset_name: "refunds",
    dataset_version: 3,
    environment_id: null,
    status: "completed",
    purpose: "manual",
    paired: false,
    from_recordings: false,
    live_reads: false,
    reruns: 2,
    estimate_usd: "0.050000",
    rerun_ceiling_usd: "0.020000",
    cost_usd: "0.040000",
    cost_is_partial: false,
    attempts_done: 4,
    attempts_total: 4,
    cases: 4,
    first_done: 4,
    first_total: 4,
    outcome: null,
    error: null,
    created_by_user_id: "u1",
    created_at: "2026-10-14T10:00:00Z",
    started_at: "2026-10-14T10:00:01Z",
    ended_at: "2026-10-14T10:02:00Z",
    arms: [arm()],
    ...overrides,
  };
}

export function attempt(overrides: Partial<EvalAttempt> = {}): EvalAttempt {
  return {
    id: "attempt-1",
    arm_id: "arm-1",
    attempt: 0,
    status: "done",
    agent_run_id: "r1",
    // i18n-exempt: an agent's answer in a fixture, not console copy
    answer: "You have 30 days.",
    calls: [],
    cost_usd: "0.010000",
    cost_is_partial: false,
    input_tokens: 100,
    output_tokens: 20,
    latency_ms: 500,
    error: null,
    outcome: true,
    score: null,
    ...overrides,
  };
}

export function evalCase(overrides: Partial<EvalCase> = {}): EvalCase {
  return {
    case_id: "case-1",
    case_revision_id: "rev-1",
    position: 0,
    // i18n-exempt: a dataset case's question in a fixture, not console copy
    input: "How long do I have to return it?",
    tags: ["refunds"],
    expectation: null,
    attempts: [attempt()],
    ...overrides,
  };
}

export const CANDIDATE_ESTIMATE: ArmEstimate = {
  role: "candidate",
  source: "draft",
  version_number: null,
  model_profile_id: "m1",
  model_label: "gpt-4.1",
  cost_per_case_usd: "0.010000",
  cost_usd: "0.200000",
  basis: "history",
  cached_from_run_id: null,
  cached_at: null,
};

export const FLIP: CaseFlip = {
  case_id: "case-1",
  flip: "regression",
  confirmed: true,
  baseline: true,
  candidate: false,
  baseline_reruns: [],
  candidate_reruns: [false, false],
  tags: ["refunds"],
};

export const ESTIMATE: EvalRunEstimate = {
  cases: 20,
  arms: [
    CANDIDATE_ESTIMATE,
    {
      role: "baseline",
      source: "version",
      version_number: 6,
      model_profile_id: "m1",
      model_label: "gpt-4.1",
      cost_per_case_usd: "0",
      cost_usd: "0",
      basis: "cached",
      cached_from_run_id: "run-0",
      cached_at: "2026-10-14T09:00:00Z",
    },
  ],
  judge_usd: "0.100000",
  total_usd: "0.300000",
  rerun_ceiling_usd: "0.600000",
  agent_remaining_usd: "10",
  org_remaining_usd: "100",
  agent_after_usd: "9.800000",
  org_after_usd: "99.700000",
  affordable: true,
};

export function comparison(overrides: Partial<EvalComparison> = {}): EvalComparison {
  return {
    candidate: {
      run_id: "run-1",
      arm_id: "arm-1",
      role: "candidate",
      source: "version",
      version_number: 7,
      model_label: "gpt-4.1",
      dataset_version: 3,
      finished_at: "2026-10-14T10:02:00Z",
    },
    baseline: {
      run_id: "run-0",
      arm_id: "arm-0",
      role: "candidate",
      source: "draft",
      version_number: null,
      model_label: "gpt-4.1",
      dataset_version: 3,
      finished_at: null,
    },
    paired: false,
    verdict: "inconclusive",
    p_value: 1,
    invalid_reason: null,
    regressions_confirmed: 1,
    regressions_unconfirmed: 0,
    fixed_confirmed: 0,
    fixed_unconfirmed: 1,
    compared: 4,
    not_compared: 0,
    candidate_summary: SUMMARY,
    baseline_summary: SUMMARY,
    efficiency: {
      cost_per_pass: "worse",
      avg_tokens: "better",
      p50_ms: "unchanged",
      p95_ms: "unknown",
    },
    cases: [FLIP],
    flips_by_tag: { refunds: { regression: 1 } },
    ...overrides,
  };
}
