import type { EvidenceItem } from "@/types/authoring";

/** Durable improvement sessions; question and answer text stays behind runs:view. */
export type ImprovementStatus =
  | "queued"
  | "running"
  | "waiting"
  | "ready"
  | "stopped"
  | "failed"
  | "cancelled"
  | "stale"
  | "accepted"
  | "published"
  | "rejected";
export type ImprovementStage =
  | "analyzing"
  | "classifying"
  | "drafting"
  | "searching"
  | "proposing"
  | "filtering"
  | "evaluating"
  | "judging";
/** How a session's attempts reach their candidate: one proposal, or a search of many. */
export type ImprovementMode = "steps" | "search";
/** How a search attempt tries variants of the agent's instructions. */
export interface SearchOptions {
  budget_usd: string;
  /** Grades variants on training questions; null grades on the dataset's judge model. */
  grading_model_profile_id?: string | null;
  max_variants?: number;
  per_generation?: number;
  minibatch?: number;
  patience?: number;
}
/** One variant a search tried; its score is on training questions, not a verdict. */
export interface SearchVariant {
  id: string;
  generation: number;
  parent_id: string | null;
  status: "pending" | "scored" | "failed";
  train_score: number | null;
  cases_scored: number;
  cases_passed: number;
  cost_usd: string;
  rationale: string;
  instructions: string;
}
export type SearchEnd =
  "budget" | "max_variants" | "patience" | "proposal" | "questions" | "no_variant";
/** Where an attempt's search is, what it spent and the best variants it found. */
export interface VariantSearch {
  budget_usd: string;
  cost_usd: string;
  grading_model_profile_id: string | null;
  max_variants: number;
  per_generation: number;
  patience: number;
  questions: number;
  generation: number;
  tried: number;
  pending: number;
  seed_score: number | null;
  best_score: number | null;
  stop_reason: SearchEnd | null;
  chosen_variant_id: string | null;
  top: SearchVariant[];
}
/** Why a waiting session's next step cannot be taken; the session's questions are fixed. */
export interface NextStepBlocked {
  reason: "missing_holdout";
  /** How many more gradable questions kept aside the check needs. */
  needed: number;
}
/** Why Try again would be refused, said before anyone presses it. */
export interface TryAgainBlocked {
  reason: "nothing_to_learn" | "missing_holdout";
  /** With missing_holdout, how many more gradable questions another attempt needs. */
  needed?: number | null;
}
/** A session waiting for a person, as a list of them shows it. */
export interface ImprovementAwaiting {
  id: string;
  agent_id: string;
  agent_name: string;
  status: ImprovementStatus;
  stage: ImprovementStage | null;
  iteration: number;
  max_iterations: number;
  created_at: string;
  next_step_blocked?: NextStepBlocked | null;
}
export interface ImprovementTarget {
  dataset_id?: string;
  suite_id?: string;
  improver_agent_id?: string;
  window_days?: number;
  max_iterations?: number;
  mode?: ImprovementMode;
  search?: SearchOptions | null;
}
export interface ImprovementEstimate {
  proposal_usd: string;
  knowledge_usd?: string;
  eval_usd: string;
  per_round_usd: string;
  total_usd: string;
  max_iterations: number;
  cases: number;
  /** How many questions the first attempt is measured on, as its analysis will count them. */
  held_out?: number | null;
  evidence_runs: number;
  /** A search's own budget, counted in the total with the check of the variant it finds. */
  search_usd?: string;
  /** How many training questions the first attempt learns from; a search needs ten. */
  train_questions?: number | null;
  /** About how long the session takes if every round runs. */
  estimated_minutes: number;
  affordable: boolean;
  reason: string | null;
}
/** How far one side of a check has answered; a reused side answered in an earlier run. */
export interface CheckAnswers {
  answered: number;
  total: number;
  reused?: boolean;
}
/** One criterion on an attempt's held-out questions, first answers counted. */
export interface VerdictCriterion {
  scorer: string;
  name: string;
  graded: number;
  before: number;
  after: number;
  /** Questions it went from fail to pass on, confirmed by asking again. */
  fixed: number;
  /** Questions it went from pass to fail on, confirmed by asking again. */
  broken: number;
  /** The skill the session's improver put this still-failing criterion down to. */
  skill?: string | null;
  skill_id?: string | null;
}
/**
 * One family of criteria on an attempt's held-out questions, counted case by case: it
 * passes in a question when every criterion of it does.
 */
export interface VerdictFamily {
  family: string;
  /** How many criteria are counted in it. */
  criteria: number;
  cases: number;
  before: number;
  after: number;
  /** Questions that hold fixed: every flipped one when settled, else the confirmed ones. */
  fixed: number;
  broken: number;
  /** Its own flipped questions were enough to tell its direction without asking again. */
  settled: boolean;
  better: boolean;
  worse: boolean;
  /** The skill the session's improver put this family down to. */
  skill?: string | null;
  skill_id?: string | null;
}
export type ImprovementVerdict =
  "better" | "criteria_better" | "no_change" | "criteria_worse" | "regression" | "inconclusive";
export type VerdictDetail = Record<
  string,
  string | number | null | VerdictCriterion[] | VerdictFamily[]
>;
export interface ImprovementIteration {
  id: string;
  number: number;
  authoring_request_id: string | null;
  batch_id: string | null;
  eval_run_ids: string[];
  candidate_spec_hash: string | null;
  included_hunk_ids?: string[] | null;
  /** What the person who asked for this attempt told its helper. */
  note?: string | null;
  previous_eval_run_ids?: string[];
  attribution_eval_run_ids: Record<string, string>;
  dropped_hunk_ids: string[];
  dropped: { hunk_id: string; reason: string }[];
  verdict: ImprovementVerdict | null;
  verdict_detail: VerdictDetail | null;
  /** How many questions the attempt is measured on; null until known. */
  held_out?: number | null;
  cost_usd: string;
  started_at: string;
  ended_at: string | null;
  /** A search attempt's progress and the variants it found. */
  variant_search?: VariantSearch | null;
}
export interface Improvement {
  published_version_id?: string | null;
  published_version?: number | null;
  next_version?: number | null;
  offer_automatic_check?: boolean;
  can_restart?: boolean;
  can_discard?: boolean;
  id: string;
  agent_id: string;
  /** Set on a skill's session, which improves the skill rather than `agent_id`. */
  skill_id?: string | null;
  /** A skill's session: what accepting it did to the skill. */
  outcome?: string | null;
  created_by_user_id: string | null;
  improver_agent_id: string | null;
  status: ImprovementStatus;
  stage: ImprovementStage | null;
  iteration: number;
  max_iterations: number;
  base_version_id: string | null;
  dataset_id: string;
  dataset_version: number;
  suite_id: string | null;
  estimate_usd: string;
  budget_usd: string;
  spent_usd: string;
  best_iteration_id: string | null;
  mode?: ImprovementMode;
  /** What Next step starts at a stop: writing changes, searching for them, or testing them. */
  next_step?: "propose" | "search" | "check" | null;
  next_step_blocked?: NextStepBlocked | null;
  try_again_blocked?: TryAgainBlocked | null;
  stop_reason: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  iterations: ImprovementIteration[];
  knowledge_eval_run_ids?: string[];
  /** Knowledge documents set aside with Not now in this session. */
  deferred_topic_ids?: string[];
  /** How far the first attempt's check has asked the agent as it is today. */
  baseline_answers?: CheckAnswers | null;
  /** How far the current attempt's check has asked the changed agent. */
  candidate_answers?: CheckAnswers | null;
  /** Whether the test told the versions apart; absent while working or without runs:view. */
  measurement_noise?: MeasurementNoise | null;
  /** Why another attempt probably won't help, read from the attempts so far; never a stop. */
  round_hint?: "no_change" | "inconclusive" | null;
  timeline: {
    action: string;
    at: string;
    stage: string | null;
    status: string | null;
    reason: string | null;
    /** The person whose action this was; absent for the session's own steps. */
    actor_user_id?: string | null;
    /** Their name, for a reader who may see the member directory. */
    actor_name?: string | null;
  }[];
}
export interface AttributionEstimate {
  changes: number;
  total_usd: string;
  affordable: boolean;
  already_started: boolean;
}

export interface KnowledgeCheckTarget {
  mode?: "context" | "retrieval";
  topic_id: string;
  round: number;
  case_ids: string[];
}
export interface KnowledgeCheckEstimate {
  total_usd: string;
  affordable: boolean;
  can_measure: boolean;
  cases: number;
  excluded: number;
  supported: boolean;
  draft_hash: string;
  reason: string | null;
}

/** The document added since to cover what an answer was missing. */
export interface KnowledgeAdded {
  document_id: string;
  filename: string;
  knowledge_base_id: string;
  added_at: string | null;
}

/** How one check or judge criterion graded a test answer. */
export interface EvidenceGrade {
  scorer: "check" | "trajectory" | "judge" | "reference";
  name: string;
  status: "pass" | "fail" | "skipped" | "error";
  reason: string;
}
export interface ImprovementEvidenceItem {
  run_id: string;
  conversation_id: string | null;
  kind: "chat" | "train_eval";
  status: string;
  rating: number;
  question: string | null;
  answer: string | null;
  comments: string[];
  /** How a test question's answer was graded. */
  grades?: EvidenceGrade[];
  branch: "agent" | "missing_knowledge" | "not_a_problem" | "unknown";
  reason: string | null;
  /** The knowledge gap topic its miss joined; examples sharing one are one problem. */
  topic_id?: string | null;
  /** Set when its topic is covered now: nothing is left to draft for it. */
  knowledge_added?: KnowledgeAdded | null;
  /** The skills the agent itself used in its run, where the reader may see them. */
  skills?: { skill_id: string; name: string }[];
}
export interface ImprovementEvidence {
  items: ImprovementEvidenceItem[];
  sample_limit: number;
  training_failures: number;
}

export interface SelectionEstimate {
  suggestions: number;
  total_usd: string;
  affordable: boolean;
  candidate_hash: string;
}

export interface ContinuationEstimate {
  mode: "next_step" | "next_round" | "resume" | "retry";
  number: number;
  /** The most the step may cost. */
  total_usd: string;
  /** What it most likely costs, without asking again. */
  expected_usd?: string;
  budget_usd: string;
  affordable: boolean;
  candidate_hash: string;
}

/** One held-out question's grades in one attempt, the first answer then each re-ask. */
export interface NoisyAttempt {
  number: number;
  baseline: (boolean | null)[];
  candidate: (boolean | null)[];
}

/** Whether a session's checks could tell a better version from a worse one. */
export interface MeasurementNoise {
  noisy: boolean;
  held_out: number;
  /** Today's version's scores, on the held-out questions the attempts share only. */
  baseline_low: number | null;
  baseline_high: number | null;
  baseline_spread: number | null;
  unstable: number;
  /** Questions graded both ways on re-asking within an attempt. */
  within: number;
  /** Held-out questions two attempts or more had in common. */
  shared: number;
  /** Shared questions today's version was graded differently on; null when too few are shared. */
  between: number | null;
  too_few_shared: boolean;
  by_attempt: { number: number; baseline_unstable: number; candidate_unstable: number }[];
  examples: { case_id: string; input: string; attempts: NoisyAttempt[] }[];
}

/** How the agent reads one of its skills now. */
export interface ImprovementSkillBinding {
  state: "main" | "pinned" | "fork";
  version: { id: string; number: number; fork_id: string | null };
  fork: { id: string; name: string; base_number: number; changes: number } | null;
  behind_main: number;
}

/** A problem the session's helper found in a skill rather than in the agent. */
export interface ImprovementSkillProblem {
  problem: string;
  evidence: EvidenceItem[];
}

/** One skill the agent reads, as its Improve session sees it. */
export interface ImprovementSkill {
  skill_id: string;
  name: string;
  /** Null where the reader may not see the skill. */
  binding: ImprovementSkillBinding | null;
  /** Visible agents an Improve of the skill's line would change. */
  agents_on_line: number | null;
  hidden_agents: number;
  problems: ImprovementSkillProblem[];
  can_improve: boolean;
  update: { kind: "update_pinned" | "catch_up_fork"; to_version: number } | null;
}

export interface ImprovementSkills {
  items: ImprovementSkill[];
}
