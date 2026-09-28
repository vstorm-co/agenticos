/**
 * API client for the workflow registry and the node catalog (#1786/#1787).
 *
 * Thin wrappers over `apiClient`, one per route in
 * `backend/app/api/routes/v1/workflows.py`. The editor's hooks
 * (`use-workflows.ts`) call these; components never call them directly.
 */

import { apiClient } from "@/lib/api-client";
import type {
  NodeCatalog,
  WorkflowCreate,
  WorkflowDetail,
  WorkflowDraftUpdate,
  WorkflowList,
  WorkflowPublish,
  WorkflowRead,
  WorkflowVersionDetail,
  WorkflowVersionList,
  WorkflowVersionRead,
} from "@/lib/workflows/types";

const ROOT = "/workflows";

/** Every registered node type, for the editor's palette. */
export async function getNodeCatalog(): Promise<NodeCatalog> {
  return apiClient.get<NodeCatalog>(`${ROOT}/node-catalog`);
}

/** One page of the workflows this member can see — their own, plus what was shared. */
export async function listWorkflows(params?: {
  skip?: number;
  limit?: number;
}): Promise<WorkflowList> {
  const query =
    params && (params.skip !== undefined || params.limit !== undefined)
      ? {
          params: {
            skip: String(params.skip ?? 0),
            limit: String(params.limit ?? 50),
          },
        }
      : undefined;
  return apiClient.get<WorkflowList>(ROOT, query);
}

/** Create a workflow in draft, with an empty graph. It cannot run until published. */
export async function createWorkflow(input: WorkflowCreate): Promise<WorkflowRead> {
  return apiClient.post<WorkflowRead>(ROOT, input);
}

/** One workflow with the graph currently being edited. */
export async function getWorkflow(workflowId: string): Promise<WorkflowDetail> {
  return apiClient.get<WorkflowDetail>(`${ROOT}/${workflowId}`);
}

/** Every published version of this workflow, newest first. Lean - no graphs. */
export async function listWorkflowVersions(workflowId: string): Promise<WorkflowVersionList> {
  return apiClient.get<WorkflowVersionList>(`${ROOT}/${workflowId}/versions`);
}

/** One published version with its frozen graph, for a read-only preview. */
export async function getWorkflowVersion(
  workflowId: string,
  versionId: string,
): Promise<WorkflowVersionDetail> {
  return apiClient.get<WorkflowVersionDetail>(`${ROOT}/${workflowId}/versions/${versionId}`);
}

/**
 * Replace the draft graph, if it is still at `expected_revision`.
 *
 * A stale revision answers `REVISION_CONFLICT` (409) naming the current one; the
 * autosave that owns this call reads it and retries. The response carries the
 * new `draft_revision` the next save must send.
 */
export async function updateWorkflowDraft(
  workflowId: string,
  update: WorkflowDraftUpdate,
): Promise<WorkflowDetail> {
  return apiClient.patch<WorkflowDetail>(`${ROOT}/${workflowId}/draft`, update);
}

/** Validate the draft graph server-side and freeze it as the version that runs. */
export async function publishWorkflow(
  workflowId: string,
  publish: WorkflowPublish,
): Promise<WorkflowVersionRead> {
  return apiClient.post<WorkflowVersionRead>(`${ROOT}/${workflowId}/publish`, publish);
}
