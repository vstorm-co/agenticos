/**
 * API client for the newest lines across every workflow the caller may view:
 * `GET /workflow-logs`. Thin wrapper over `apiClient`; `use-recent-workflow-logs.ts`
 * calls it.
 */

import { apiClient } from "@/lib/api-client";
import type { WorkflowRecentLogs } from "@/lib/workflows/types";

/** The newest `limit` real-run lines, and the last 24 hours' counts by outcome. */
export async function getRecentWorkflowLogs(limit: number): Promise<WorkflowRecentLogs> {
  return apiClient.get<WorkflowRecentLogs>("/workflow-logs", {
    params: { skip: "0", limit: String(limit) },
  });
}
