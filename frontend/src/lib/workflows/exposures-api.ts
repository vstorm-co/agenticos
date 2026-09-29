/**
 * API client for a workflow's exposure - its webhook or schedule,
 * `backend/app/api/routes/v1/workflow_exposures.py`.
 *
 * Publishing a version whose trigger node is one of them is what makes it; here
 * it is read, paused and resumed, and a webhook's secret rotated. Thin wrappers
 * over `apiClient`, one per route; `use-workflow-exposure.ts` calls these,
 * components never do.
 */

import { apiClient } from "@/lib/api-client";
import type {
  WorkflowExposureRead,
  WorkflowExposureUpdate,
  WorkflowExposureWithSecret,
} from "@/lib/workflows/types";

const root = (workflowId: string) => `/workflows/${workflowId}`;

/** The webhook or schedule the live version starts from, or null when it starts another way. */
export async function getWorkflowExposure(
  workflowId: string,
): Promise<WorkflowExposureRead | null> {
  return apiClient.get<WorkflowExposureRead | null>(`${root(workflowId)}/exposure`);
}

export async function updateWorkflowExposure(
  workflowId: string,
  exposureId: string,
  body: WorkflowExposureUpdate,
): Promise<WorkflowExposureRead> {
  return apiClient.patch<WorkflowExposureRead>(`${root(workflowId)}/exposures/${exposureId}`, body);
}

/** A new signing secret for a webhook; the old one stops verifying at once. */
export async function rotateWorkflowExposureSecret(
  workflowId: string,
  exposureId: string,
): Promise<WorkflowExposureWithSecret> {
  return apiClient.post<WorkflowExposureWithSecret>(
    `${root(workflowId)}/exposures/${exposureId}/rotate-secret`,
  );
}
