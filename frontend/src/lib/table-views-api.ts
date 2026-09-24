/** Typed client for Table Views (the backend's per-table `views` resource), on `api-client.ts`. */

import { apiClient } from "./api-client";
import type {
  TableViewCreate,
  TableViewList,
  TableViewRead,
  TableViewUpdate,
  ViewKind,
} from "@/types/tables";

/**
 * The views the console's picker offers for one kind: the largest page the
 * server answers, the caller's own first, narrowed by the server rather than
 * after the fact - a page shared by every kind could leave a tab's own views
 * off it. More than that many of one kind offers the first 100.
 */
const VIEW_PAGE_LIMIT = 100;

export function listViews(tableId: string, kind?: ViewKind): Promise<TableViewList> {
  const params: Record<string, string> = { limit: String(VIEW_PAGE_LIMIT) };
  if (kind) params.kind = kind;
  return apiClient.get<TableViewList>(`/tables/${tableId}/views`, { params });
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
