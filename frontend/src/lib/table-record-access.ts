import type { RecordRead } from "@/types/tables";

/** Older servers omit authority; an explicit current answer always takes precedence. */
export function canWriteRecord(record: RecordRead, tableCanEdit: boolean): boolean {
  return record.access === undefined ? tableCanEdit : record.access === "write";
}

export function canWriteCell(record: RecordRead, columnId: string, tableCanEdit: boolean): boolean {
  return canWriteRecord(record, tableCanEdit) && !record.read_only_column_ids?.includes(columnId);
}

export function canDeleteRecord(record: RecordRead, tableCanEdit: boolean): boolean {
  return record.can_delete ?? tableCanEdit;
}
