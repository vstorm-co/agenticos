import type { SkillCheck, SkillCheckAgent } from "@/types/skill-checks";
import type { SkillImprovement } from "@/types/skill-improvement";
import { SESSION } from "./improvement";
import { checkAgent as baseAgent, finishedCheck } from "./skill-checks";

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

/** A check row named and stated for a test, its fixed and broken counts to match. */
export function checkAgent(
  name: string,
  state: SkillCheckAgent["state"],
  overrides: Partial<SkillCheckAgent> = {},
): SkillCheckAgent {
  const id = name.toLowerCase();
  const row = baseAgent({ name, state });
  return {
    ...row,
    agent: { id, name },
    stages: [{ ...row.stages[0]!, eval_run_id: `run-${id}` }],
    fixed: state === "better" ? 2 : 0,
    broken: state === "worse" ? 1 : 0,
    fixed_confirmed: state === "better" ? 2 : 0,
    regressions_confirmed: state === "worse" ? 1 : 0,
    ...overrides,
  };
}

/** A finished check on main's skill `k1`, with one agent better and one unchanged. */
export function skillCheck(overrides: Partial<SkillCheck> = {}): SkillCheck {
  return finishedCheck({
    id: "c1",
    skill_id: "k1",
    proposal_id: null,
    outcomes: ["improve_further", "apply", "discard"],
    agents: [checkAgent("Support", "better"), checkAgent("Sales", "no_change")],
    ...overrides,
  });
}
