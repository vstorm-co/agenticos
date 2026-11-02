/**
 * A skill's improvement session: the same steps as an agent's, on one line of the
 * skill - main or a fork - checked on every agent of that line.
 */

import type { Improvement, ImprovementEstimate, ImprovementIteration } from "@/types/improvement";
import type { SkillCheckAgent } from "@/types/skill-checks";

export interface SkillImprovementIteration extends ImprovementIteration {
  /** The check that measured this attempt on the line's agents. */
  check_id: string | null;
}

export interface SkillImprovement extends Omit<Improvement, "iterations"> {
  skill_id: string;
  /** The line it improves; null is main. */
  fork_id: string | null;
  line_name: string;
  iterations: SkillImprovementIteration[];
}

export interface SkillImprovementEstimate extends ImprovementEstimate {
  /** The line's agents as the check would see them, the ones without budget among them. */
  agents: SkillCheckAgent[];
  hidden: number;
}

/** What Accept does with a measured attempt, beside improving further or discarding. */
export type SkillAcceptOutcome = "apply" | "apply_and_pin" | "fork_for_helped";

export interface SkillAccept {
  outcome: SkillAcceptOutcome;
  /** The person read which agents could not be checked. */
  acknowledge_unknown: boolean;
  /** The fork's name, for `fork_for_helped`. */
  fork_name?: string;
}
