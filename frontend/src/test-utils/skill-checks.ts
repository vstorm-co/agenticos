import type { SkillCheck, SkillCheckAgent } from "@/types/skill-checks";

/** A check agent row for tests: a published agent asked the skill's and its own questions. */
export function checkAgent(
  overrides: Partial<SkillCheckAgent> & { name?: string } = {},
): SkillCheckAgent {
  // i18n-exempt: fixture text a test asserts on, not copy
  const { name = "Online desk", ...rest } = overrides;
  return {
    agent: { id: `agent-${name}`, name },
    via_specialist: null,
    agent_version: 3,
    state: "queued",
    unknown_reason: null,
    sample: "own_questions",
    stages: [
      {
        kind: "skill_set",
        dataset_id: "d-1",
        // i18n-exempt: fixture text a test asserts on, not copy
        dataset_name: "Skill set",
        cases: 4,
        eval_run_id: null,
        counts: null,
      },
      {
        kind: "dataset_sample",
        dataset_id: "d-2",
        dataset_name: "Own",
        cases: 2,
        eval_run_id: null,
        counts: null,
      },
    ],
    fixed: 0,
    broken: 0,
    held_out: 0,
    fixed_confirmed: 0,
    regressions_confirmed: 0,
    noisy: false,
    expected_usd: "0.08",
    at_most_usd: "0.24",
    ...rest,
  };
}

/** A finished check for tests. */
export function finishedCheck(overrides: Partial<SkillCheck> = {}): SkillCheck {
  return {
    id: "c-1",
    skill_id: "s-1",
    status: "done",
    verdict: "passed",
    warnings: [],
    outcomes: ["apply", "improve_further", "discard"],
    outcome: null,
    proposal_id: "p-1",
    // i18n-exempt: fixture text a test asserts on, not copy
    candidate: { description: "Refunds", content: "Refund within 30 days." },
    applied_version_id: null,
    created_at: "2026-11-03T00:00:00Z",
    finished_at: "2026-11-03T00:05:00Z",
    line: { fork_id: null, name: "main" },
    base_version: { id: "v-3", number: 3, fork_id: null },
    mode: "quick",
    description_changed: false,
    agents: [checkAgent({ state: "better" })],
    hidden: 0,
    hidden_unknown: 0,
    expected_usd: "0.08",
    at_most_usd: "0.24",
    org_remaining_usd: null,
    affordable: true,
    ...overrides,
  };
}
