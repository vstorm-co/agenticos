/**
 * API client for a workflow's runs - `backend/app/api/routes/v1/workflow_runs.py`.
 *
 * Thin wrappers over `apiClient`, one per route; `use-workflow-runs.ts` calls
 * these, components never do.
 */

import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import type {
  WorkflowGraph,
  WorkflowNodeRunList,
  WorkflowRunFile,
  WorkflowRunFileList,
  WorkflowRunList,
  WorkflowRunRead,
  WorkflowRunStart,
} from "@/lib/workflows/types";

const ROOT = "/workflow-runs";

/** The latest runs of one workflow, newest first. */
export async function listWorkflowRuns(workflowId: string): Promise<WorkflowRunList> {
  return apiClient.get<WorkflowRunList>(ROOT, {
    params: { workflow_id: workflowId, limit: "100" },
  });
}

export async function getWorkflowRun(runId: string): Promise<WorkflowRunRead> {
  return apiClient.get<WorkflowRunRead>(`${ROOT}/${runId}`);
}

/** Every step the run took, loop iterations included. */
export async function listWorkflowRunNodes(runId: string): Promise<WorkflowNodeRunList> {
  return apiClient.get<WorkflowNodeRunList>(`${ROOT}/${runId}/nodes`, {
    params: { limit: "500" },
  });
}

/** The graph the run executes: its version's, or a test run's draft snapshot. */
export async function getWorkflowRunGraph(runId: string): Promise<WorkflowGraph> {
  const { graph } = await apiClient.get<{ graph: WorkflowGraph }>(`${ROOT}/${runId}/graph`);
  return graph;
}

export async function startWorkflowRun(start: WorkflowRunStart): Promise<WorkflowRunRead> {
  return apiClient.post<WorkflowRunRead>(ROOT, start);
}

export async function cancelWorkflowRun(runId: string): Promise<WorkflowRunRead> {
  return apiClient.post<WorkflowRunRead>(`${ROOT}/${runId}/cancel`);
}

/** The files the run's steps stored, oldest first. */
export async function listWorkflowRunFiles(runId: string): Promise<WorkflowRunFileList> {
  return apiClient.get<WorkflowRunFileList>(`${ROOT}/${runId}/files`);
}

/**
 * Save one of the run's files to disk.
 *
 * Fetched with `raw` and saved from a blob rather than followed as a link: the
 * route is organization-scoped, and a bare link would arrive without the header
 * and be answered for the caller's personal organization.
 */
export async function downloadWorkflowRunFile(runId: string, file: WorkflowRunFile): Promise<void> {
  const response = await apiClient.raw(`${ROOT}/${runId}/files/${file.id}`);
  saveBlob(await response.blob(), file.filename ?? file.id);
}
