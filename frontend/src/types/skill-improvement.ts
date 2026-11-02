/**
 * A skill's improvement session: the same steps as an agent's, on one line of the
 * skill - main or a fork - checked on every agent of that line.
 */

import type {
  Improvement,
  ImprovementEstimate,
  ImprovementEvidenceItem,
  ImprovementIteration,
  ImprovementStatus,
  ImprovementStage,
  NextStepBlocked,
} from "@/types/improvement";
import type { CheckOutcome, CheckVerdict, SkillCheck, SkillCheckAgent } from "@/types/skill-checks";
import type { SkillVersionRef } from "@/types/skill-versions";

export interface SkillImprovementIteration extends ImprovementIteration {
  /** The check that measured this attempt on the line's agents. */
  check_id: string | null;
  check_verdict: CheckVerdict | null;
  /** A changed description decides when agents open the skill, so it is checked in full. */
  description_changed?: boolean;
}

export interface SkillImprovement extends Omit<Improvement, "iterations"> {
  skill_id: string;
  /** The line it improves; null is main. */
  fork_id: string | null;
  line_name: string;
  base_version: SkillVersionRef;
  iterations: SkillImprovementIteration[];
  /** The current attempt's check on the line's agents. */
  check: SkillCheck | null;
  /** What may be done with the measured attempt, as its check decided. */
  outcomes: CheckOutcome[];
  outcome: "applied" | "applied_pinned" | "forked" | "discarded" | null;
  applied_version_id: string | null;
  agents: number;
  hidden_agents: number;
  expires_at: string | null;
}

export interface SkillImprovementEstimate extends Omit<ImprovementEstimate, "knowledge_usd"> {
  line: { fork_id: string | null; name: string };
  /** The line's agents as the check would see them, the ones without budget among them. */
  agents: SkillCheckAgent[];
  hidden_agents: number;
}

/** A problem found in answers where the line's versions were loaded, and where it occurs. */
export interface SkillProblem {
  title: string;
  summary: string;
  runs: number;
  agents: { id: string; name: string; runs: number }[];
  hidden_agents: number;
  examples: ImprovementEvidenceItem[];
}

export interface SkillProblems {
  problems: SkillProblem[];
  /** Answers whose trouble lies elsewhere than in the skill. */
  not_the_skill: number;
  not_a_problem: number;
  /** Answers from before skill loads were recorded, which cannot be attributed. */
  usage_unknown: number;
}

/** A skill session that waits for a person, wherever its skill is. */
export interface SkillImprovementAwaiting {
  id: string;
  skill_id: string;
  skill_name: string;
  fork_id: string | null;
  line_name: string;
  status: ImprovementStatus;
  stage: ImprovementStage | null;
  iteration: number;
  max_iterations: number;
  created_at: string;
  next_step_blocked?: NextStepBlocked | null;
}
