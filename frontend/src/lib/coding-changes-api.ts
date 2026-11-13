/**
 * What one coding-agent task changed (#2480): its files, each with its part of the patch.
 *
 * Read by the id a `run_coding_agent` report names, and authorised as the transcript
 * is - whoever may read the conversation the task ran in.
 */

import { apiClient } from "./api-client";

export type ChangeStatus = "added" | "modified" | "deleted" | "renamed";

export interface ChangedFile {
  path: string;
  old_path: string | null;
  status: ChangeStatus;
  additions: number;
  deletions: number;
  binary: boolean;
  /** The file's section of a unified diff; null once the patch ran past its ceiling. */
  patch: string | null;
  /** This file's section was cut part way. */
  truncated: boolean;
}

export interface CodingTaskChanges {
  id: string;
  conversation_id: string;
  harness: string;
  files: ChangedFile[];
  /** Changed files past the ceiling on how many are listed. */
  omitted: number;
  /** Anything - a file, or part of the patch - was left out. */
  truncated: boolean;
  created_at: string;
  can_revert: boolean;
  reverted_at: string | null;
  revert_status: "pending" | "unknown" | "failed" | null;
  revert_conflicting_files: string[];
}

export async function revertCodingChanges(changeId: string): Promise<CodingTaskChanges> {
  return apiClient.post<CodingTaskChanges>(
    `/conversations/coding-changes/${encodeURIComponent(changeId)}/revert`,
  );
}

export async function readCodingChanges(changeId: string): Promise<CodingTaskChanges> {
  return apiClient.get<CodingTaskChanges>(
    `/conversations/coding-changes/${encodeURIComponent(changeId)}`,
  );
}
