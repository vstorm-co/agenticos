/**
 * Datasets - the versioned test cases an agent's evals run over.
 *
 * Mirrors `app/schemas/dataset.py`. A case is read through a version: `id` is
 * the revision a version holds, `case_id` the case across its edits.
 */

import type { DatasetScoring } from "./scoring";
import type { Visibility } from "./sharing";

export type CaseSource = "manual" | "import" | "conversation" | "synthetic";
export type DatasetChange = "add" | "edit" | "remove" | "import" | "generate";
export type DatasetSort = "name" | "updated";
export type DatasetFileFormat = "csv" | "jsonl";
/** How an agent's calls are matched against the expected ones. */
export type ToolOrderMode = "any" | "in_order" | "exact";

export interface CaseMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ExpectedToolCall {
  tool: string;
  args: Record<string, unknown>;
}

/**
 * One rule the answer is scored against, named by `type`, its parameters beside it.
 * Which types exist is scoring's to say (`app/schemas/scoring.py`); the server
 * refuses one it does not know.
 */
export interface CaseCheck {
  type: string;
  [parameter: string]: unknown;
}

/** Everything a person writes about one case. */
export interface DatasetCaseContent {
  input: string;
  history: CaseMessage[];
  reference_answer: string | null;
  counter_example: string | null;
  expected_tool_calls: ExpectedToolCall[];
  order_mode: ToolOrderMode;
  checks: CaseCheck[];
  tags: string[];
  note: string | null;
}

export interface DatasetCase extends DatasetCaseContent {
  improvement_partition?: "train" | "holdout";
  masked?: boolean;
  id: string;
  case_id: string;
  source: CaseSource;
  source_run_id: string | null;
  source_conversation_id: string | null;
  source_message_id: string | null;
  /** The knowledge base document a generated case's passage came from. */
  source_document_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  /** When erasing the person it was taken from replaced its text; eval runs skip it until rewritten. */
  anonymised_at?: string | null;
}

export interface DatasetCaseList {
  items: DatasetCase[];
  total: number;
  /** The version these cases are from; 0 before any case exists. */
  version: number;
}

/** What the newest version's cases test against. The four expectations overlap; the sources sum to the case count. */
/** How many cases hold one combination of what a scorer reads. */
export interface ExpectationMix {
  checks: boolean;
  tool_calls: boolean;
  reference: boolean;
  cases: number;
}

export interface DatasetStats {
  train_cases?: number;
  holdout_cases?: number;
  with_reference: number;
  with_counter_example: number;
  with_tool_calls: number;
  with_checks: number;
  /** Cases counted by whether each has checks, expected calls and a reference at once. */
  expectation_mix: ExpectationMix[];
  by_source: Record<CaseSource, number>;
  /** The most used tags, most used first. */
  top_tags: { tag: string; cases: number }[];
  tag_groups?: {
    tags: string[];
    cases: number;
    checks: boolean;
    tool_calls: boolean;
    reference: boolean;
  }[];
}

export type RunNeed = "runs:view" | "datasets:run";

export interface Dataset {
  improvement_holdout_share?: string;
  id: string;
  name: string;
  description: string | null;
  visibility: Visibility;
  owner_user_id: string | null;
  /** The agent the dataset was made to test - an agent's test set names it. */
  agent_id: string | null;
  latest_version: number;
  case_count: number;
  /** Whether the caller may change this dataset's cases. */
  can_edit: boolean;
  /** Whether the caller may run this dataset - start an eval on it, score against it. */
  can_run: boolean;
  /** What the caller lacks to run it, empty when `can_run`: reading runs, this dataset, or both. */
  run_needs: RunNeed[];
  /** Generated cases waiting for a decision; 0 for a caller who may not decide. */
  pending_proposals: number;
  /** How this dataset's cases are scored. */
  scoring: DatasetScoring;
  /** The judge grading it - its own or the default one; null when that judge is gone. */
  judge_name: string | null;
  stats: DatasetStats;
  created_at: string;
  updated_at: string | null;
}

export interface DatasetList {
  items: Dataset[];
  total: number;
}

export interface DatasetVersion {
  id: string;
  number: number;
  case_count: number;
  change: DatasetChange;
  changed_cases: number;
  created_by_user_id: string | null;
  created_at: string;
}

export interface DatasetVersionList {
  items: DatasetVersion[];
  total: number;
}
