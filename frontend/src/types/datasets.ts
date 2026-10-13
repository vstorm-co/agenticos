/**
 * Datasets - the versioned test cases an agent's evals run over.
 *
 * Mirrors `app/schemas/dataset.py`. A case is read through a version: `id` is
 * the revision a version holds, `case_id` the case across its edits.
 */

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
 * Which types exist is scoring's to say; a dataset only keeps them.
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
}

export interface DatasetCaseList {
  items: DatasetCase[];
  total: number;
  /** The version these cases are from; 0 before any case exists. */
  version: number;
}

export interface Dataset {
  id: string;
  name: string;
  description: string | null;
  visibility: Visibility;
  owner_user_id: string | null;
  latest_version: number;
  case_count: number;
  /** Whether the caller may change this dataset's cases. */
  can_edit: boolean;
  /** Generated cases waiting for a decision; 0 for a caller who may not decide. */
  pending_proposals: number;
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
