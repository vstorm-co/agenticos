import type { SkillCheck, SkillCheckAgent } from "@/types/skill-checks";
import type { SkillImprovement } from "@/types/skill-improvement";
import { SESSION } from "./improvement";

/** A skill session on main, measured once and waiting at its result. */
export function skillSession(overrides: Partial<SkillImprovement> = {}): SkillImprovement {
  return {
    ...SESSION,
    agent_id: "",
    skill_id: "k1",
    fork_id: null,
    line_name: "main",
    base_version: { id: "m12", number: 12 },
    iterations: SESSION.iterations.map((round) => ({
      ...round,
      check_id: "c1",
      check_verdict: "passed",
    })),
    check: skillCheck(),
    outcomes: ["improve_further", "apply", "discard"],
    outcome: null,
    applied_version_id: null,
    agents: 2,
    hidden_agents: 0,
    expires_at: null,
    ...overrides,
  };
}

export function checkAgent(
  name: string,
  state: SkillCheckAgent["state"],
  overrides: Partial<SkillCheckAgent> = {},
): SkillCheckAgent {
  return {
    agent: { id: name.toLowerCase(), name },
    via_specialist: null,
    agent_version: 3,
    state,
    unknown_reason: null,
    sample: "own_questions",
    stages: [
      {
        kind: "skill_set",
        dataset_id: "ts",
        dataset_name: "returns-policy questions",
        cases: 10,
        eval_run_id: `run-${name.toLowerCase()}`,
      },
    ],
    fixed: state === "better" ? 2 : 0,
    broken: state === "worse" ? 1 : 0,
    held_out: 10,
    fixed_confirmed: state === "better" ? 2 : 0,
    regressions_confirmed: state === "worse" ? 1 : 0,
    noisy: false,
    expected_usd: "0.02",
    at_most_usd: "0.05",
    ...overrides,
  };
}

export function skillCheck(overrides: Partial<SkillCheck> = {}): SkillCheck {
  return {
    id: "c1",
    skill_id: "k1",
    status: "done",
    line: { fork_id: null, name: "main" },
    base_version: { id: "m12", number: 12, fork_id: null },
    mode: "quick",
    description_changed: false,
    agents: [checkAgent("Support", "better"), checkAgent("Sales", "no_change")],
    hidden: 0,
    expected_usd: "0.04",
    at_most_usd: "0.10",
    org_remaining_usd: "10.00",
    affordable: true,
    verdict: "passed",
    warnings: [],
    outcomes: ["improve_further", "apply", "discard"],
    outcome: null,
    hidden_unknown: 0,
    proposal_id: null,
    applied_version_id: null,
    created_at: "2026-11-02T10:00:00Z",
    finished_at: "2026-11-02T10:05:00Z",
    ...overrides,
  };
}
