/**
 * API client for the decisions workflow steps wait on -
 * `backend/app/api/routes/v1/workflow_approvals.py`.
 */

import { apiClient } from "@/lib/api-client";
import type { WorkflowApprovalList, WorkflowApprovalRead } from "@/lib/workflows/types";

const ROOT = "/workflow-approvals";

/** The organization's pending requests, oldest first. */
export async function listWorkflowApprovals(): Promise<WorkflowApprovalList> {
  return apiClient.get<WorkflowApprovalList>(ROOT);
}

/** Approve or reject one request, which wakes the step waiting on it. */
export async function decideWorkflowApproval(
  id: string,
  approved: boolean,
): Promise<WorkflowApprovalRead> {
  return apiClient.post<WorkflowApprovalRead>(`${ROOT}/${id}`, { approved });
}
