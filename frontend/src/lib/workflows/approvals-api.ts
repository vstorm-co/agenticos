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

/**
 * The requests already answered or lapsed in a window, newest first - the record
 * the Approvals tab keeps beside the tool calls' own. `status` repeats, so the
 * parameters are pairs.
 */
export async function listDecidedWorkflowApprovals(range: {
  from: string;
  to: string;
}): Promise<WorkflowApprovalList> {
  return apiClient.get<WorkflowApprovalList>(ROOT, {
    params: [
      ["status", "approved"],
      ["status", "rejected"],
      ["status", "expired"],
      ["created_from", range.from],
      ["created_to", range.to],
      ["oldest_first", "false"],
    ],
  });
}
