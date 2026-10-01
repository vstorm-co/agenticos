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
 *
 * Given the viewer's `locale`, a date reads as that locale writes one - "Oct 4,
 * 2026", "4 paź 2026" - and a date and time in the viewer's own zone; without
 * one, as it is stored. A date has no zone, so it is read as the day it names.
 */
export function formatCellValue(
  column: ColumnDef,
  value: CellValue,
  boolLabel: (value: boolean) => string,
  locale?: string,
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
    case "datetime": {
      if (typeof value !== "string") return "";
      const dated = locale === undefined ? null : localDate(column.type, value, locale);
      return dated ?? value;
    }
    default:
      return String(value);
  }
}

/** A stored date or date-time as `locale` writes it, or null when it is not one. */
function localDate(type: "date" | "datetime", value: string, locale: string): string | null {
  const date = new Date(type === "date" ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(
    locale,
    type === "date"
      ? { dateStyle: "medium", timeZone: "UTC" }
      : { dateStyle: "medium", timeStyle: "short" },
  ).format(date);
}
