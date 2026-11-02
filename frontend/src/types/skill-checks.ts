/**
 * A skill change checked on every agent of its line.
 *
 * Each agent comes out better, no change, within noise, worse, or unknown - with
 * the reason it could not be measured. Hidden agents are counted, never named.
 */

import type { SkillVersionRef } from "@/types/skill-versions";

export type SkillCheckMode = "quick" | "thorough";

export type SkillCheckAgentState =
  "queued" | "running" | "better" | "no_change" | "within_noise" | "worse" | "unknown";

export type SkillCheckUnknownReason =
  "no_questions" | "no_access" | "no_budget" | "no_published_version" | "failed";

export interface AgentRef {
  id: string;
  name: string;
}

export interface SkillCheckStage {
  /** The skill's own test questions, a sample of the agent's, or the agent's whole set. */
  kind: "skill_set" | "dataset_sample" | "dataset";
  dataset_id: string;
  dataset_name: string;
  cases: number;
  eval_run_id: string | null;
  fixed: number;
  broken: number;
  held_out: number;
  regressions_confirmed: number;
  fixed_confirmed: number;
  noisy: boolean;
}

export interface SkillCheckAgent {
  agent: AgentRef;
  via_specialist: string | null;
  agent_version: number | null;
  state: SkillCheckAgentState;
  unknown_reason: SkillCheckUnknownReason | null;
  /**
   * In a quick check, whether the agent was asked its own questions too, or only the
   * skill's - having none of its own where it loaded the skill. Null in a thorough one.
   */
  sample: "own_questions" | "skill_set_only" | null;
  stages: SkillCheckStage[];
  expected_usd: string;
  at_most_usd: string;
  cost_usd: string;
}

export interface SkillCheckEstimate {
  line: { fork_id: string | null; name: string };
  base_version: SkillVersionRef;
  mode: SkillCheckMode;
  /** A changed description decides when agents open the skill, so it forces a thorough check. */
  description_changed: boolean;
  agents: SkillCheckAgent[];
  /** Agents of the line the caller may not see. */
  hidden: number;
  expected_usd: string;
  at_most_usd: string;
  org_remaining_usd: string | null;
  affordable: boolean;
}

export type SkillCheckVerdict = "passed" | "blocked" | "no_better" | "needs_ack";

export type SkillCheckOutcome =
  "improve_further" | "apply" | "apply_and_pin" | "fork_for_helped" | "discard";

export interface SkillCheck extends SkillCheckEstimate {
  id: string;
  status: string;
  verdict: SkillCheckVerdict | null;
  warnings: ("within_noise" | "other_environments")[];
  /** What may be done with the result, and only that: the server decides. */
  outcomes: SkillCheckOutcome[];
  /** Unknown agents among the hidden ones. */
  hidden_unknown: number;
  proposal_id: string | null;
  created_at: string;
  finished_at: string | null;
}
