/**
 * API client for a table's triggers - the workflows it runs when a record is
 * added (`backend/app/api/routes/v1/virtual_table_triggers.py`). Publishing a
 * workflow whose trigger node is "New table record" makes one; here they are
 * read, paused and resumed.
 */

import { apiClient } from "./api-client";
import type {
  TableTriggerAdmissionList,
  TableTriggerList,
  TableTriggerRead,
  TableTriggerUpdate,
} from "@/types/tables";

const root = (tableId: string) => `/tables/${tableId}/triggers`;

export async function listTableTriggers(tableId: string): Promise<TableTriggerList> {
  return apiClient.get<TableTriggerList>(root(tableId));
}

export async function updateTableTrigger(
  tableId: string,
  triggerId: string,
  body: TableTriggerUpdate,
): Promise<TableTriggerRead> {
  return apiClient.patch<TableTriggerRead>(`${root(tableId)}/${triggerId}`, body);
}

/** What each added record led to, newest first. */
export async function listTableTriggerAdmissions(
  tableId: string,
  triggerId: string,
): Promise<TableTriggerAdmissionList> {
  return apiClient.get<TableTriggerAdmissionList>(`${root(tableId)}/${triggerId}/admissions`, {
    params: { limit: "50" },
  });
}
