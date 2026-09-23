/** Typed client for Table Views (the backend's per-table `views` resource), on `api-client.ts`. */

import { apiClient } from "./api-client";
import type {
  TableViewCreate,
  TableViewList,
  TableViewRead,
  TableViewUpdate,
  ViewKind,
} from "@/types/tables";

export function listViews(tableId: string, kind?: ViewKind): Promise<TableViewList> {
  return apiClient.get<TableViewList>(`/tables/${tableId}/views`, {
    params: kind ? { kind } : undefined,
  });
}

export function createView(tableId: string, data: TableViewCreate): Promise<TableViewRead> {
  return apiClient.post<TableViewRead>(`/tables/${tableId}/views`, data);
}

export function getView(tableId: string, viewId: string): Promise<TableViewRead> {
  return apiClient.get<TableViewRead>(`/tables/${tableId}/views/${viewId}`);
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
