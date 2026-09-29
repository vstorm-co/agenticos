/**
 * API client for a workflow's exposures - its webhooks and schedules,
 * `backend/app/api/routes/v1/workflow_exposures.py`.
 *
 * Thin wrappers over `apiClient`, one per route; `use-workflow-exposures.ts`
 * calls these, components never do.
 */

import { apiClient } from "@/lib/api-client";
import type {
  WorkflowExposureCreate,
  WorkflowExposureCreated,
  WorkflowExposureList,
  WorkflowExposureRead,
  WorkflowExposureUpdate,
} from "@/lib/workflows/types";

const root = (workflowId: string) => `/workflows/${workflowId}/exposures`;

export async function listWorkflowExposures(workflowId: string): Promise<WorkflowExposureList> {
  return apiClient.get<WorkflowExposureList>(root(workflowId));
}

export async function createWorkflowExposure(
  workflowId: string,
  body: WorkflowExposureCreate,
): Promise<WorkflowExposureCreated> {
  return apiClient.post<WorkflowExposureCreated>(root(workflowId), body);
}

export async function updateWorkflowExposure(
  workflowId: string,
  exposureId: string,
  body: WorkflowExposureUpdate,
): Promise<WorkflowExposureRead> {
  return apiClient.patch<WorkflowExposureRead>(`${root(workflowId)}/${exposureId}`, body);
}

export async function deleteWorkflowExposure(
  workflowId: string,
  exposureId: string,
): Promise<void> {
  await apiClient.delete(`${root(workflowId)}/${exposureId}`);
}

/** A new signing secret for a webhook; the old one stops verifying at once. */
export async function rotateWorkflowExposureSecret(
  workflowId: string,
  exposureId: string,
): Promise<WorkflowExposureCreated> {
  return apiClient.post<WorkflowExposureCreated>(`${root(workflowId)}/${exposureId}/rotate-secret`);
}
