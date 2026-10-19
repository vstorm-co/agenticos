/**
 * Scoring - how a dataset's cases are scored, and what scoring found.
 *
 * Mirrors `app/schemas/scoring.py`.
 */

import type { CaseCheck, ExpectedToolCall, ToolOrderMode } from "./datasets";

export type ScorerKind = "check" | "trajectory" | "judge" | "reference";
export type ScorerStatus = "pass" | "fail" | "skipped" | "error";
export type ReviewState = "none" | "pending" | "done";
export type ReviewSelect = "none" | "failed" | "all";
/** What counts for a score: a person's decision where there is one, the scorers' otherwise. */
export type ScoreOutcome = "failed" | "not_graded" | "passed";

export interface RubricCriterion {
  name: string;
  description: string;
  required: boolean;
}

export interface DatasetScoring {
  checks: { enabled: boolean; required: boolean; defaults: CaseCheck[] };
  trajectory: { enabled: boolean; required: boolean };
  judge: {
    enabled: boolean;
    /** The dataset's own judge; null is the default eval judge. */
    agent_id: string | null;
    /** Withdrawn and always null: a judge grades on the model its own page sets. */
    model_profile_id: string | null;
    scale_max: number;
    pass_at: number;
    criteria: RubricCriterion[];
  };
  reference: { enabled: boolean; required: boolean };
  review: { select: ReviewSelect };
}

/**
 * What one scorer found. `score` is 0..1; `reason_code` names why a scorer was
 * skipped or could not run, so each cause reads - and is fixed - on its own.
 */
export interface ScorerResult {
  scorer: ScorerKind;
  name: string;
  required: boolean;
  status: ScorerStatus;
  score: number | null;
  reason: string;
  reason_code: string | null;
  /** What the judge quoted from the answer that the answer does not hold. */
  unverified_quotes: string[];
  /** The rule the judge says its grade follows from. */
  rule: string | null;
  /** A top grade with nothing quoted from the answer to show for it. */
  unverified: boolean;
  /** The start of an answer the judge gave that could not be read. */
  judge_said: string | null;
  judge_run_id: string | null;
}

/**
 * One run's answer scored against one case. `passed` is the scorers' conclusion
 * (null: a required scorer could not run); `human_passed` a person's verdict;
 * `outcome` the one that counts.
 */
/** Which judge graded a score; two scores compare only when every field matches. */
export interface JudgePin {
  agent_id: string | null;
  model_profile_id: string | null;
  agent_version_id: string | null;
  spec_version: number | null;
  rubric_hash: string;
  /** The version of the task every judge is handed; null on a score graded before it was kept. */
  prompt_version: number | null;
}

export interface CaseScore {
  id: string;
  dataset_id: string;
  case_id: string;
  case_revision_id: string;
  /** What the scored revision expected, which a later edit of the case does not change. */
  question: string;
  reference_answer: string | null;
  expected_tool_calls: ExpectedToolCall[];
  order_mode: ToolOrderMode;
  checks: CaseCheck[];
  case_tags: string[];
  /** The answer as scored, capped and with secrets redacted; null once its owner was erased. */
  answer: string | null;
  run_id: string | null;
  /** The model the scored run answered on, while the run is kept. */
  run_model: string | null;
  /** The agent that answered, and which of its versions; the name and number while they exist. */
  agent_id: string | null;
  agent_version_id: string | null;
  agent_name: string | null;
  agent_version: number | null;
  /** The name of the model the judge graded on, while it exists. */
  judge_model: string | null;
  /** True for a reader who may not view the agent that answered: the answer, and every result's reason and quotes, are left out. */
  answer_hidden: boolean;
  /** The eval run that scored it; null for a score asked for by hand. */
  eval_run_id: string | null;
  results: ScorerResult[];
  judge: JudgePin | null;
  passed: boolean | null;
  /** Why `passed` is null: the reason code of the first required scorer that reached no verdict. */
  unscored_reason: string | null;
  review_state: ReviewState;
  human_passed: boolean | null;
  human_note: string | null;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  created_by_user_id: string | null;
  created_at: string;
  outcome: boolean | null;
}

/** How often people agreed with a judge: `agreed` of the `decided` scores it graded. */
export interface JudgeAgreement {
  agreed: number;
  decided: number;
}

/** What scoring again changed: the scores scored anew, and the ids that needed nothing. */
export interface Rescored {
  rescored: CaseScore[];
  kept: string[];
}

export interface CaseScoreList {
  items: CaseScore[];
  total: number;
}

/** A score in the review queue, with the dataset it belongs to. */
export interface PendingScore extends CaseScore {
  dataset_name: string;
}

/** How many scores wait in one dataset, by what the scorers concluded. */
export interface PendingDataset {
  dataset_id: string;
  name: string;
  failed: number;
  unscored: number;
  passed: number;
}

/** A page of the review queue, oldest first, and every dataset holding any of it. */
export interface ReviewQueue {
  items: PendingScore[];
  total: number;
  datasets: PendingDataset[];
}
