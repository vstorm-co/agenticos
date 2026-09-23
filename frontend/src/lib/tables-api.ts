/**
 * Typed client for Virtual Tables (the backend's `tables` resource), on `api-client.ts`.
 *
 * One function per route; every hook that touches a table or its records goes
 * through this file rather than calling `apiClient` inline, so the wire shape
 * lives in one place.
 */

import { apiClient } from "./api-client";
import type {
  RecordCreate,
  RecordList,
  RecordQuery,
  RecordRead,
  RecordUpdate,
  SchemaUpdate,
  TableCreate,
  TableList,
  TableRead,
  TableUpdate,
} from "@/types/tables";

export interface TableListQuery {
  search?: string;
  includeArchived?: boolean;
  skip?: number;
  limit?: number;
}

export function listTables(query: TableListQuery = {}): Promise<TableList> {
  const params: Record<string, string> = {};
  if (query.search) params.q = query.search;
  if (query.includeArchived) params.include_archived = "true";
  params.skip = String(query.skip ?? 0);
  params.limit = String(query.limit ?? 50);
  return apiClient.get<TableList>("/tables", { params });
}

export function createTable(data: TableCreate): Promise<TableRead> {
  return apiClient.post<TableRead>("/tables", data);
}

export function getTable(tableId: string): Promise<TableRead> {
  return apiClient.get<TableRead>(`/tables/${tableId}`);
}

export function updateTable(tableId: string, data: TableUpdate): Promise<TableRead> {
  return apiClient.patch<TableRead>(`/tables/${tableId}`, data);
}

export function archiveTable(tableId: string): Promise<TableRead> {
  return apiClient.post<TableRead>(`/tables/${tableId}/archive`);
}

export function updateSchema(tableId: string, data: SchemaUpdate): Promise<TableRead> {
  return apiClient.put<TableRead>(`/tables/${tableId}/schema`, data);
}

export function queryRecords(tableId: string, query: RecordQuery): Promise<RecordList> {
  return apiClient.post<RecordList>(`/tables/${tableId}/records/query`, query);
}

export function createRecord(tableId: string, data: RecordCreate): Promise<RecordRead> {
  return apiClient.post<RecordRead>(`/tables/${tableId}/records`, data);
}

export function getRecord(tableId: string, recordId: string): Promise<RecordRead> {
  return apiClient.get<RecordRead>(`/tables/${tableId}/records/${recordId}`);
}

export function updateRecord(
  tableId: string,
  recordId: string,
  data: RecordUpdate,
): Promise<RecordRead> {
  return apiClient.patch<RecordRead>(`/tables/${tableId}/records/${recordId}`, data);
}

export function deleteRecord(
  tableId: string,
  recordId: string,
  expectedRevision: number,
): Promise<void> {
  return apiClient.delete<void>(
    `/tables/${tableId}/records/${recordId}?expected_revision=${expectedRevision}`,
  );
}
