import { apiClient } from "./api-client";
import type { GrantSubject } from "@/types/sharing";
import type { RowPolicy, TableRead } from "@/types/tables";

export type RecordAccessLevel = "read" | "write";

export interface RecordGrant {
  id: string;
  subject_user_id: string | null;
  subject_email: string | null;
  subject_group_id: string | null;
  subject_group_name: string | null;
  level: RecordAccessLevel;
  expires_at: string | null;
}

export interface RecordAccess {
  table_id: string;
  record_id: string;
  grants: RecordGrant[];
}

export interface RecordGrantInput {
  subject_user_id?: string;
  subject_group_id?: string;
  level: RecordAccessLevel;
  expires_at?: string | null;
}

const accessPath = (tableId: string, recordId: string) =>
  `/tables/${tableId}/records/${recordId}/access`;

export function getRecordAccess(tableId: string, recordId: string): Promise<RecordAccess> {
  return apiClient.get(accessPath(tableId, recordId));
}

export function setRecordGrant(
  tableId: string,
  recordId: string,
  input: RecordGrantInput,
): Promise<RecordAccess> {
  return apiClient.put(`${accessPath(tableId, recordId)}/grants`, input);
}

export function revokeRecordGrant(
  tableId: string,
  recordId: string,
  subject: GrantSubject,
): Promise<void> {
  const segment = subject.kind === "group" ? "group-grants" : "grants";
  return apiClient.delete(`${accessPath(tableId, recordId)}/${segment}/${subject.id}`);
}

export function setTableRowPolicy(tableId: string, policy: RowPolicy): Promise<TableRead> {
  return apiClient.put(`/tables/${tableId}/row-policy`, policy);
}
