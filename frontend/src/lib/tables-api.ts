/**
 * Typed client for Virtual Tables (the backend's `tables` resource), on `api-client.ts`.
 *
 * One function per route; every hook that touches a table or its records goes
 * through this file rather than calling `apiClient` inline, so the wire shape
 * lives in one place.
 */

import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import { saveBlob } from "./file-access";
import type {
  RecordBatchFailure,
  RecordBatchResult,
  RecordCount,
  RecordCountQuery,
  RecordCreate,
  RecordExportQuery,
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
  /** `updated_at` orders most-recently-changed first; the server default is `name`. */
  sort?: "name" | "updated_at";
  skip?: number;
  limit?: number;
}

export function listTables(query: TableListQuery = {}): Promise<TableList> {
  const params: Record<string, string> = {};
  if (query.search) params.q = query.search;
  if (query.includeArchived) params.include_archived = "true";
  if (query.sort) params.sort = query.sort;
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

export function countRecords(tableId: string, query: RecordCountQuery): Promise<RecordCount> {
  return apiClient.post<RecordCount>(`/tables/${tableId}/records/count`, query);
}

/** Records created together, each on its own - at most 200 in one call. */
export function createRecords(
  tableId: string,
  records: RecordCreate[],
): Promise<RecordBatchResult> {
  return apiClient.post<RecordBatchResult>(`/tables/${tableId}/records/batch`, { records });
}

/**
 * One refused record of a batch as the error a single create would have thrown,
 * so it is shown the way every other refusal is - in the reader's language where
 * its code has a translation.
 */
export function batchRefusal(failure: RecordBatchFailure): ApiError {
  return new ApiError(422, failure.message, {
    error: { code: failure.code, message: failure.message, details: failure.details },
  });
}

/** The records a query matches, as a CSV file saved to disk under the name the server gives. */
export async function exportRecords(tableId: string, query: RecordExportQuery): Promise<void> {
  const response = await apiClient.raw(`/tables/${tableId}/records/export`, {
    method: "POST",
    body: query,
  });
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "table.csv";
  saveBlob(await response.blob(), name);
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
