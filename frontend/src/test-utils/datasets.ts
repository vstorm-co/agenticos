import { DEFAULT_SCORING } from "@/lib/scoring";
import type { Dataset } from "@/types/datasets";

export function datasetFixture(overrides: Partial<Dataset> = {}): Dataset {
  const count = overrides.case_count ?? 2;
  return {
    id: "d1",
    name: "Returns",
    description: null,
    visibility: "org",
    owner_user_id: null,
    agent_id: null,
    latest_version: 1,
    case_count: count,
    can_edit: true,
    can_run: true,
    run_needs: [],
    pending_proposals: 0,
    scoring: structuredClone(DEFAULT_SCORING),
    judge_name: null,
    stats: {
      with_reference: count,
      with_counter_example: 0,
      with_tool_calls: 0,
      with_checks: 0,
      expectation_mix: [{ checks: false, tool_calls: false, reference: true, cases: count }],
      by_source: { manual: count, import: 0, conversation: 0, synthetic: 0 },
      top_tags: [],
    },
    created_at: "2026-11-09T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}
