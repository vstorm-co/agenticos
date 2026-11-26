"use client";

import { useLocale, useTranslations } from "next-intl";

import { useTable, useTableRecord } from "@/hooks/use-tables";
import { formatCellValue, recordCellText } from "@/lib/format-cell-value";
import { useMediaSurface } from "@/lib/generated-media";
import type { TableCall } from "@/lib/table-tool-calls";
import type { CellValue, ColumnDef, RecordRead, TableRead } from "@/types/tables";

/**
 * How much of one value a summary shows. A `long_text` cell holds up to 100,000
 * characters, and the summary sits outside the folded details on an approval
 * card, so the whole of it stays in the raw arguments instead.
 */
const PREVIEW = 280;

function preview(text: string): string {
  return text.length > PREVIEW ? `${text.slice(0, PREVIEW - 1)}…` : text;
}

function raw(value: CellValue): string {
  return Array.isArray(value) ? value.join(", ") : String(value);
}

/**
 * A cell as the table's own views show it, given its column; the raw value
 * without one, or when the column cannot read it.
 *
 * A call is read through the table as it is now, not as it was: a value sent
 * as text before its column became a select is no option id, and formatting
 * it would show nothing where something was written.
 */
export function useCellText(): (column: ColumnDef | undefined, value: CellValue) => string {
  const t = useTranslations("tables.cells");
  const locale = useLocale();
  return (column, value) => {
    if (column === undefined) return preview(raw(value));
    const text = formatCellValue(column, value, (on) => t(on ? "true" : "false"), locale);
    return preview(text === "" && value !== null && value !== "" ? raw(value) : text);
  };
}

/** A cell of a record the API returned, its links named by the labels the record carries. */
export function useRecordText(): (column: ColumnDef, record: RecordRead) => string {
  const t = useTranslations("tables.cells");
  const locale = useLocale();
  return (column, record) =>
    preview(recordCellText(column, record, (on) => t(on ? "true" : "false"), locale));
}

/**
 * The table a call names, when this reader may see it.
 *
 * Never read on a hosted page: its visitor has no session, so the request could
 * only be refused, and the call is shown as it was sent instead.
 */
export function useCallTable(call: TableCall | null): TableRead | null {
  const surface = useMediaSurface();
  const { table } = useTable(surface.kind === "session" && call !== null ? call.tableId : null);
  return table ?? null;
}

/**
 * The record a call names, as it is now, when this reader may see it. Mounted
 * only under a table this reader already read, so never on a hosted page.
 */
export function useCallRecord(call: TableCall): RecordRead | null {
  const { record } = useTableRecord(call.tableId, call.recordId);
  return record ?? null;
}
