"use client";

import { useLocale, useTranslations } from "next-intl";

import { useTable } from "@/hooks/use-tables";
import { formatCellValue } from "@/lib/format-cell-value";
import { useMediaSurface } from "@/lib/generated-media";
import type { TableCall } from "@/lib/table-tool-calls";
import type { CellValue, ColumnDef, TableRead } from "@/types/tables";

/** A cell as the table's own views show it, given its column; the raw value without one. */
export function useCellText(): (column: ColumnDef | undefined, value: CellValue) => string {
  const t = useTranslations("tables.cells");
  const locale = useLocale();
  return (column, value) => {
    if (column === undefined) return Array.isArray(value) ? value.join(", ") : String(value);
    return formatCellValue(column, value, (on) => t(on ? "true" : "false"), locale);
  };
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
