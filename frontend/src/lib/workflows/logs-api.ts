/**
 * API client for a workflow's log - the lines its steps' quick logs wrote:
 * `GET /workflows/{id}/logs`, `GET /workflows/{id}/logs/summary` and
 * `GET /workflow-runs/{id}/logs`.
 *
 * Thin wrappers over `apiClient`; `use-workflow-logs.ts` calls these.
 */

import { apiClient } from "@/lib/api-client";
import type { LogQuery, WorkflowLogList } from "@/lib/workflows/types";

/** Lines a Logs page shows at once. */
export const LOG_PAGE = 50;

/** One page of a workflow's log, newest first, filtered on the server. */
export async function listWorkflowLogs(query: LogQuery): Promise<WorkflowLogList> {
  const params: [string, string][] = [
    ["skip", String(query.page * LOG_PAGE)],
    ["limit", String(LOG_PAGE)],
  ];
  if (query.nodeInstanceId !== undefined) params.push(["node_instance_id", query.nodeInstanceId]);
  // Repeated, as the route reads a list: a line counts when it left by any of them.
  for (const outcome of query.outcomes ?? []) params.push(["outcome", outcome]);
  if (query.from !== undefined) params.push(["from", query.from]);
  if (query.q !== undefined && query.q !== "") params.push(["q", query.q]);
  if (query.run !== undefined && query.run !== "") params.push(["run", query.run]);
  if (query.includeTest) params.push(["include_test", "true"]);
  return apiClient.get<WorkflowLogList>(`/workflows/${query.workflowId}/logs`, { params });
}

/** The most lines the run route answers in one page (`limit: le=500`). */
const RUN_LOGS_PAGE = 500;

/** Every line the run's steps wrote, in the order they were written - every page of them. */
export async function listRunLogs(runId: string): Promise<WorkflowLogList> {
  const page = (skip: number) =>
    apiClient.get<WorkflowLogList>(`/workflow-runs/${runId}/logs`, {
      params: { skip: String(skip), limit: String(RUN_LOGS_PAGE) },
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
