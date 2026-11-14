/**
 * A skill's improvement session: the same steps as an agent's, on one line of the
 * skill - main or a fork - checked on every agent of that line.
 */

import type {
  ContinuationEstimate,
  Improvement,
  ImprovementIteration,
  ImprovementStatus,
  ImprovementStage,
  NextStepBlocked,
} from "@/types/improvement";
import type {
  CheckOutcome,
  CheckVerdict,
  SkillCheck,
  SkillCheckEstimate,
} from "@/types/skill-checks";
import type { SkillVersionRef } from "@/types/skill-versions";

/** What a session is for: improving its line, or merging a fork with main. */
export type SkillImprovementPurpose = "improve" | "catch_up" | "to_main";

/** What a merge session's result offers beside a check's own outcomes. */
export type MergeOutcome = "catch_up" | "return_to_main";

export interface SkillImprovementIteration extends ImprovementIteration {
  /** The check that measured this attempt on the line's agents. */
  check_id: string | null;
  check_verdict: CheckVerdict | null;
  /** A changed description decides when agents open the skill, so it is checked in full. */
  description_changed?: boolean;
}

export interface SkillImprovement extends Omit<Improvement, "iterations"> {
  skill_id: string;
  /** Who started it, for a reader who may see the member directory. */
  created_by?: { id: string; name: string | null } | null;
  /** The line it improves; null is main. */
  fork_id: string | null;
  line_name: string;
  base_version: SkillVersionRef;
  iterations: SkillImprovementIteration[];
  /** The current attempt's check on the line's agents. */
  check: SkillCheck | null;
  /** What may be done with the measured attempt, as its check decided. */
  outcomes: (CheckOutcome | MergeOutcome)[];
  /** The line moved past the version the result was checked on: check again before deciding. */
  stale?: boolean;
  outcome:
    "applied" | "applied_pinned" | "forked" | "discarded" | "caught_up" | "returned_to_main" | null;
  /** Absent from sessions read before merging existed, which all improve. */
  purpose?: SkillImprovementPurpose;
  /** For a move to main, the fork whose changes it takes. */
  source_fork_id?: string | null;
  /** For a catch-up or a move to main, the merge Changes shows and edits. */
  merge_id?: string | null;
  /**
   * A catch-up's second check, of main's newest version alone: `off` when it was not
   * asked for, `same` when the merge is main anyway, `checked` when it ran.
   */
  main_alone?: "off" | "same" | "checked" | null;
  main_alone_check?: SkillCheck | null;
  applied_version_id: string | null;
  agents: number;
  hidden_agents: number;
  expires_at: string | null;
}

export interface SkillImprovementEstimate {
  line: { fork_id: string | null; name: string };
  base_version: SkillVersionRef;
  /** Grouping the problems, then one proposal. */
  proposal_usd: string;
  per_round_usd: string;
  /** What the session spends before it first waits for a person. */
  total_usd: string;
  max_iterations: number;
  evidence_runs: number;
  /** Answers from before skill loads were recorded, which are not read. */
  usage_unknown: number;
  /** Agents of the line the caller may see; each is named when its check is priced. */
  agents: number;
  hidden_agents: number;
  estimated_minutes: number;
  affordable: boolean;
  reason: "no_evidence" | null;
}

/** A next step's price; for a check, the agents it runs on and the ones it cannot. */
export interface SkillContinuationEstimate extends ContinuationEstimate {
  check_estimate?: SkillCheckEstimate | null;
  /** For a catch-up, what checking main alone adds; included in the total. */
  main_alone_usd?: string | null;
  main_alone_estimate?: SkillCheckEstimate | null;
}

/** What forking a session's change did: the fork, and who moved onto it and how. */
export interface SkillImprovementForked {
  session: SkillImprovement;
  fork: { id: string; name: string };
  /** Moved and published where each agent publishes. */
  moved: { id: string; name: string }[];
  /** Moved only in the draft, which waits to be published. */
  draft_only: { id: string; name: string }[];
}

/** A passage of one run that shows a problem, checked word for word against it. */
export interface SkillProblemExample {
  run_id: string;
  /** Null for a reader who may not read runs: the example is named, not quoted. */
  quote: string | null;
}

/** A problem found in answers where the line's versions were loaded, and where it occurs. */
export interface SkillProblem {
  title: string;
  summary: string;
  runs: number;
  agents: { id: string; name: string; runs: number }[];
  hidden_agents: number;
  examples: SkillProblemExample[];
  /** Examples from runs the reader may not see, counted and never shown. */
  hidden_examples: number;
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
