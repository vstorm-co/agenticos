/**
 * API client for a workflow's exposure - its webhook or schedule,
 * `backend/app/api/routes/v1/workflow_exposures.py`.
 *
 * Publishing a version whose trigger node is one of them is what makes it; here
 * it is read, paused and resumed, and a webhook's secret rotated - and, before
 * any of that, a draft's test URL opened and read. Thin wrappers
 * over `apiClient`, one per route; `use-workflow-exposure.ts` calls these,
 * components never do.
 */

import { apiClient } from "@/lib/api-client";
import type {
  WebhookTestCapture,
  WebhookTestListening,
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

/** A test URL for the draft's webhook: the next call to it is kept, never run. */
export async function listenForWebhookTest(workflowId: string): Promise<WebhookTestListening> {
  return apiClient.post<WebhookTestListening>(`${root(workflowId)}/webhook-test`);
}

/** Whether a test URL still waits, and the call it caught. */
export async function getWebhookTest(
  workflowId: string,
  token: string,
): Promise<WebhookTestCapture> {
  return apiClient.get<WebhookTestCapture>(`${root(workflowId)}/webhook-test/${token}`);
}
