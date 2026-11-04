/**
 * API client for a model step's evals,
 * `backend/app/api/routes/v1/workflow_evals.py`. Thin wrappers over `apiClient`,
 * one per route; `use-step-evals.ts` calls these, components never do.
 */

import { apiClient } from "@/lib/api-client";
import type { EvalCase, EvalCaseCreate, EvalCaseList, EvalRun } from "@/lib/workflows/types";

const step = (workflowId: string, nodeId: string) => `/workflows/${workflowId}/steps/${nodeId}`;

/** The step's cases, and how its latest try went. */
export async function listStepEvals(workflowId: string, nodeId: string): Promise<EvalCaseList> {
  return apiClient.get<EvalCaseList>(`${step(workflowId, nodeId)}/evals`);
}

/** A new case for the step. */
export async function createStepEval(
  workflowId: string,
  nodeId: string,
  input: EvalCaseCreate,
): Promise<EvalCase> {
  return apiClient.post<EvalCase>(`${step(workflowId, nodeId)}/evals`, input);
}

/** Remove a case. */
export async function deleteStepEval(workflowId: string, evalId: string): Promise<void> {
  await apiClient.delete(`/workflows/${workflowId}/evals/${evalId}`);
}

/** Start a test run of the step for each of its cases. */
export async function tryStepEvals(workflowId: string, nodeId: string): Promise<EvalRun> {
  return apiClient.post<EvalRun>(`${step(workflowId, nodeId)}/eval-runs`);
}
