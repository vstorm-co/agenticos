/**
 * A change to a skill checked on every agent of the line it would change.
 *
 * Mirrors `backend/app/schemas/skill_check.py`. Money arrives as decimal strings.
 */

export type CheckMode = "quick" | "thorough";
export type CheckStatus = "running" | "done" | "cancelled" | "applied" | "forked" | "discarded";
export type CheckVerdict = "passed" | "blocked" | "no_better" | "needs_ack";
export type AgentCheckState =
  "queued" | "running" | "better" | "no_change" | "within_noise" | "worse" | "unknown";
export type UnknownReason =
  | "no_questions"
  | "no_access"
  | "no_budget"
  | "no_published_version"
  | "inconclusive"
  | "failed"
  | "unscorable"
  | "all_evidence"
  | "cancelled"
  | "own_not_asked";
export type CheckOutcome =
  "improve_further" | "apply" | "apply_and_pin" | "fork_for_helped" | "discard";

export interface SkillCheckStart {
  fork_id: string | null;
  proposal_id?: string;
  candidate?: { description: string; content: string };
  /** For a candidate text: the version it was written over, refused once the line moves on. */
  base_version_id?: string;
  mode?: CheckMode;
}

export interface CheckStage {
  kind: "skill_set" | "dataset_sample" | "dataset";
  dataset_id: string;
  /** Null for a dataset the reader may not see. */
  dataset_name: string | null;
  cases: number;
  eval_run_id: string | null;
  /**
   * The stage's held-out questions, candidate against baseline, kept when the agent
   * was judged; null before that, for an older check, or a dataset the reader may not see.
   */
  counts: StageCounts | null;
}

export interface StageCounts {
  /** Answered and graded on both sides: fixed, broken or unchanged. */
  compared: number;
  fixed: number;
  broken: number;
  unchanged: number;
  /** Held out but not compared: unanswered or ungraded on a side, or changed between. */
  unknown: number;
}

export interface SkillCheckAgent {
  agent: { id: string; name: string };
  via_specialist: string | null;
  agent_version: number | null;
  state: AgentCheckState;
  unknown_reason: UnknownReason | null;
  /** In a quick check: whether the agent's own questions were asked, or only the skill's. */
  sample: "own_questions" | "skill_set_only" | "own_not_asked" | null;
  stages: CheckStage[];
  fixed: number;
  broken: number;
  held_out: number;
  fixed_confirmed: number;
  regressions_confirmed: number;
  noisy: boolean;
  expected_usd: string;
  at_most_usd: string;
}

export interface SkillCheckEstimate {
  line: { fork_id: string | null; name: string };
  base_version: { id: string; number: number; fork_id: string | null };
  mode: CheckMode;
  description_changed: boolean;
  agents: SkillCheckAgent[];
  /** Agents of the line the caller may not see, counted and never named. */
  hidden: number;
  hidden_unknown: number;
  expected_usd: string;
  at_most_usd: string;
  org_remaining_usd: string | null;
  affordable: boolean;
}

export interface SkillCheck extends SkillCheckEstimate {
  id: string;
  skill_id: string;
  /** `catch_up` for a pinned agent's update, accepted by moving that agent, never applied. */
  source?: "manual" | "proposal" | "session" | "catch_up";
  status: CheckStatus;
  verdict: CheckVerdict | null;
  warnings: "within_noise"[];
  /** What may be done with it now; empty while it runs. */
  outcomes: CheckOutcome[];
  outcome: CheckOutcome | null;
  proposal_id: string | null;
  /** No agent reads the line, so the check passed with nobody to check. */
  no_readers?: boolean;
  /** The text checked, which a person may go back to editing. */
  candidate: { description: string; content: string };
  /** The skill improvement session that started it, which decides it. */
  session_id?: string | null;
  applied_version_id: string | null;
  created_at: string;
  finished_at: string | null;
}

/** A check a person started that still runs or waits for a decision, as "Waiting for you" lists it. */
export interface SkillCheckAwaiting {
  id: string;
  skill_id: string;
  skill_name: string;
  line: { fork_id: string | null; name: string };
  status: "running" | "done";
  verdict: CheckVerdict | null;
  /** The proposed change it checks; null for a text checked by hand. */
  proposal_id: string | null;
  /** The agents it checks, counting the ones the reader may not see. */
  agents: number;
  created_at: string;
}

export interface SkillCheckFork {
  name: string;
  /** The agents that move onto the fork; left out, the ones the change helped. */
  agent_ids?: string[];
  acknowledge_unknown?: boolean;
}

export interface SkillCheckApply {
  acknowledge_unknown?: boolean;
  pin_worse?: boolean;
  note?: string;
}
