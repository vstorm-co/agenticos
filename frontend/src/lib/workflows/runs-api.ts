/**
 * API client for a workflow's runs - `backend/app/api/routes/v1/workflow_runs.py`.
 *
 * Thin wrappers over `apiClient`, one per route; `use-workflow-runs.ts` calls
 * these, components never do.
 */

import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import type {
  RunHistoryQuery,
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

/** Runs a history page shows at once. */
export const RUN_HISTORY_PAGE = 25;

/** One page of a run history, newest first, filtered on the server. */
export async function listRunHistory(query: RunHistoryQuery): Promise<WorkflowRunList> {
  const params: Record<string, string> = {
    skip: String(query.page * RUN_HISTORY_PAGE),
    limit: String(RUN_HISTORY_PAGE),
  };
  if (query.workflowId !== undefined) params["workflow_id"] = query.workflowId;
  if (query.status !== undefined) params["status"] = query.status;
  if (query.mode !== undefined) params["mode"] = query.mode;
  if (query.triggeredBy !== undefined) params["triggered_by"] = query.triggeredBy;
  if (query.createdAfter !== undefined) params["created_after"] = query.createdAfter;
  return apiClient.get<WorkflowRunList>(ROOT, { params });
}

/** Run again what a run ran, from where it stopped. */
export async function retryWorkflowRun(runId: string): Promise<WorkflowRunRead> {
  return apiClient.post<WorkflowRunRead>(`${ROOT}/${runId}/retry`);
}

export async function getWorkflowRun(runId: string): Promise<WorkflowRunRead> {
  return apiClient.get<WorkflowRunRead>(`${ROOT}/${runId}`);
}

/** The most steps the route answers in one page (`limit: le=500`). */
const NODE_RUNS_PAGE = 500;

/**
 * Every step the run took, loop iterations included - every page of them.
 *
 * A loop can take a run to thousands of steps, and the run page counts, draws and
 * lists what this returns, so one page would hide every later iteration and its
 * failures.
 */
export async function listWorkflowRunNodes(runId: string): Promise<WorkflowNodeRunList> {
  const page = (skip: number) =>
    apiClient.get<WorkflowNodeRunList>(`${ROOT}/${runId}/nodes`, {
      params: { skip: String(skip), limit: String(NODE_RUNS_PAGE) },
    });
  const first = await page(0);
  const items = [...first.items];
  while (items.length < first.total) {
    const next = await page(items.length);
    // The run shrank between pages - nothing is left to read.
    if (next.items.length === 0) break;
    items.push(...next.items);
  }
  return { items, total: first.total };
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
