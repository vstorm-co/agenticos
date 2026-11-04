import type { CellValue, ColumnDef, RecordRead, SystemColumnKey } from "@/types/tables";

export const SYSTEM_COLUMN_KEYS = ["created_at", "updated_at", "created_by", "updated_by"] as const;

/** Read-only projections of the record envelope, never writable JSONB cells. */
export const TABLE_SYSTEM_COLUMNS: ColumnDef[] = SYSTEM_COLUMN_KEYS.map((key) => ({
  id: `__${key}`,
  label: key,
  type: key.endsWith("_at") ? "datetime" : "text",
  system: key,
  nullable: true,
  default: null,
  options: [],
  archived: false,
}));

export function systemCellValue(key: SystemColumnKey, record: RecordRead): CellValue {
  if (key === "updated_at") return record.updated_at ?? record.created_at;
  return record[key] ?? null;
}
