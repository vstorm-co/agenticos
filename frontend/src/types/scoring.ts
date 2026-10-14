/**
 * Scoring - how a dataset's cases are scored, and what scoring found.
 *
 * Mirrors `app/schemas/scoring.py`.
 */

import type { CaseCheck } from "./datasets";

export type ScorerKind = "check" | "trajectory" | "judge" | "reference";
export type ScorerStatus = "pass" | "fail" | "skipped" | "error";
export type ReviewState = "none" | "pending" | "done";
export type ReviewSelect = "none" | "failed" | "all";

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
  judge_run_id: string | null;
}

/**
 * One run's answer scored against one case. `passed` is the scorers' conclusion
 * (null: a required scorer could not run); `human_passed` a person's verdict;
 * `outcome` the one that counts.
 */
/** Which judge graded a score; two scores compare only when every field matches. */
export interface JudgePin {
  model_profile_id: string | null;
  agent_version_id: string | null;
  spec_version: number | null;
  rubric_hash: string;
}

export interface CaseScore {
  id: string;
  dataset_id: string;
  case_id: string;
  case_revision_id: string;
  /** The scored revision's question and reference answer, which a later edit does not change. */
  question: string;
  reference_answer: string | null;
  run_id: string | null;
  /** The model the scored run answered on, while the run is kept. */
  run_model: string | null;
  results: ScorerResult[];
  judge: JudgePin | null;
  passed: boolean | null;
  review_state: ReviewState;
  human_passed: boolean | null;
  human_note: string | null;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  created_by_user_id: string | null;
  created_at: string;
  outcome: boolean | null;
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
