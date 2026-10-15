import type { CaseScore } from "@/types/scoring";

/**
 * A score as the server sends it, with nothing graded and nobody's decision,
 * for a test to override the few fields it is about.
 *
 * Deliberately in `test-utils`, outside the coverage `include` list.
 */
export function caseScore(overrides: Partial<CaseScore> = {}): CaseScore {
  return {
    id: "s1",
    dataset_id: "d1",
    case_id: "c1",
    case_revision_id: "r1",
    // i18n-exempt: test data the server would send, not copy the console shows of its own
    question: "How long is the return window?",
    reference_answer: null,
    expected_tool_calls: [],
    order_mode: "any",
    checks: [],
    case_tags: [],
    answer: null,
    run_id: null,
    run_model: null,
    agent_id: null,
    agent_version_id: null,
    agent_name: null,
    agent_version: null,
    judge_model: null,
    eval_run_id: null,
    results: [],
    judge: null,
    passed: null,
    unscored_reason: null,
    review_state: "none",
    human_passed: null,
    human_note: null,
    reviewed_by_user_id: null,
    reviewed_at: null,
    created_by_user_id: null,
    created_at: "2026-10-13T09:00:00Z",
    outcome: null,
    ...overrides,
  };
}
