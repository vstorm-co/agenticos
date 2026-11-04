/**
 * API client for the alert rules on a workflow's log:
 * `GET`/`POST /workflows/{id}/log-alerts` and `PATCH`/`DELETE .../{rule_id}`.
 *
 * Thin wrappers over `apiClient`; `use-workflow-log-alerts.ts` calls these.
 */

import { apiClient } from "@/lib/api-client";
import type { LogAlertInput, LogAlertPatch, LogAlertRule } from "@/lib/workflows/types";

/** Every rule on the workflow, with the last time each fired. */
export async function listLogAlerts(workflowId: string): Promise<LogAlertRule[]> {
  const list = await apiClient.get<{ items: LogAlertRule[] }>(
    `/workflows/${workflowId}/log-alerts`,
  );
  return list.items;
}

export function createLogAlert(workflowId: string, input: LogAlertInput): Promise<LogAlertRule> {
  return apiClient.post<LogAlertRule>(`/workflows/${workflowId}/log-alerts`, input);
}

export function updateLogAlert(
  workflowId: string,
  ruleId: string,
  patch: LogAlertPatch,
): Promise<LogAlertRule> {
  return apiClient.patch<LogAlertRule>(`/workflows/${workflowId}/log-alerts/${ruleId}`, patch);
}

export async function deleteLogAlert(workflowId: string, ruleId: string): Promise<void> {
  await apiClient.delete(`/workflows/${workflowId}/log-alerts/${ruleId}`);
}
