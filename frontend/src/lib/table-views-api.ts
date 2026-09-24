/** Typed client for Table Views (the backend's per-table `views` resource), on `api-client.ts`. */

import { apiClient } from "./api-client";
import type {
  TableViewCreate,
  TableViewList,
  TableViewRead,
  TableViewUpdate,
} from "@/types/tables";

/**
 * The views the console's picker offers: the largest page the server answers,
 * the caller's own first. A table with more than that many views the caller can
 * see offers the first 100.
 */
const VIEW_PAGE_LIMIT = 100;

export function listViews(tableId: string): Promise<TableViewList> {
  return apiClient.get<TableViewList>(`/tables/${tableId}/views`, {
    params: { limit: String(VIEW_PAGE_LIMIT) },
  });
}

export function createView(tableId: string, data: TableViewCreate): Promise<TableViewRead> {
  return apiClient.post<TableViewRead>(`/tables/${tableId}/views`, data);
}

export function updateView(
  tableId: string,
  viewId: string,
  data: TableViewUpdate,
): Promise<TableViewRead> {
  return apiClient.patch<TableViewRead>(`/tables/${tableId}/views/${viewId}`, data);
}

export function deleteView(tableId: string, viewId: string): Promise<void> {
  return apiClient.delete<void>(`/tables/${tableId}/views/${viewId}`);
}
