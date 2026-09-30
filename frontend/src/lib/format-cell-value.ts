import type { CellValue, ColumnDef } from "@/types/tables";

/**
 * A cell's value, formatted for read-only display in the grid, list and kanban
 * views - the one place that decides how a value of each column type reads,
 * so the three views never disagree about it.
 *
 * A `single_select`/`multi_select` value is an option id; the label is read
 * from the column's own option list (archived options included, so a record
 * that still holds one keeps showing its label rather than a bare id).
 *
 * `boolLabel` renders `true`/`false` - a module constant cannot call a
 * translator, so the caller's own `tables.cells` strings are threaded through
 * rather than this file holding an English "true"/"false" of its own.
 */
export function formatCellValue(
  column: ColumnDef,
  value: CellValue,
  boolLabel: (value: boolean) => string,
): string {
  if (value === null || value === undefined) return "";

  switch (column.type) {
    case "boolean":
      return typeof value === "boolean" ? boolLabel(value) : "";
    case "single_select": {
      const option = column.options.find((candidate) => candidate.id === value);
      return option?.label ?? "";
    }
    case "multi_select": {
      const ids = Array.isArray(value) ? value : [];
      return ids
        .map((id) => column.options.find((candidate) => candidate.id === id)?.label)
        .filter((label): label is string => !!label)
        .join(", ");
    }
    case "date":
    case "datetime":
      return typeof value === "string" ? value : "";
    default:
      return String(value);
  }
}
