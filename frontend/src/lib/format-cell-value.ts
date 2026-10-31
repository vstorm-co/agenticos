import { systemCellValue } from "./table-system-columns";
import { DEFAULT_TABLE_DISPLAY } from "@/lib/table-display";
import type { TableDisplay } from "@/types/tables";
import { markdownDocument } from "@/lib/markdown-document";
import { MAX_RATING, type CellValue, type ColumnDef, type RecordRead } from "@/types/tables";

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
  display?: TableDisplay,
): string {
  if (value === null || value === undefined) return "";

  switch (column.type) {
    case "rich_text":
      return typeof value === "string" ? markdownDocument(value).body.trim() : "";
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
    case "formula":
      // A formula answers with whatever it works out - a yes or no reads as one.
      return typeof value === "boolean" ? boolLabel(value) : String(value);
    case "lookup":
      return Array.isArray(value) ? value.map(String).join(", ") : String(value);
    case "link":
      // Ids name nothing to a reader; `recordCellText` names them from the record.
      return Array.isArray(value) ? String(value.length) : "";
    case "rating":
      return typeof value === "number"
        ? "★".repeat(value) + "☆".repeat(Math.max(0, MAX_RATING - value))
        : "";
    case "date":
    case "datetime": {
      if (typeof value !== "string") return "";
      const dated = locale === undefined ? null : localDate(column.type, value, locale, display);
      return dated ?? value;
    }
    default:
      return String(value);
  }
}

/** A stored date or date-time as `locale` writes it, or null when it is not one. */
function localDate(
  type: "date" | "datetime",
  value: string,
  locale: string,
  display: TableDisplay = DEFAULT_TABLE_DISPLAY,
): string | null {
  const date = new Date(type === "date" ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return null;
  const timeZone = type === "date" ? "UTC" : undefined;
  if (display.date_format === "locale" && display.time_format === "locale") {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: type === "datetime" ? "short" : undefined,
      timeZone,
    }).format(date);
  }
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(date);
  const part = (kind: Intl.DateTimeFormatPartTypes) =>
    parts.find((one) => one.type === kind)?.value;
  const day = part("day");
  const month = part("month");
  const year = part("year");
  const formattedDate =
    display.date_format === "iso"
      ? `${year}-${month}-${day}`
      : display.date_format === "day_first"
        ? `${day}.${month}.${year}`
        : display.date_format === "month_first"
          ? `${month}/${day}/${year}`
          : new Intl.DateTimeFormat(locale, {
              dateStyle: display.date_format === "long" ? "long" : "medium",
              timeZone,
            }).format(date);
  if (type === "date" || display.time_format === "hidden") return formattedDate;
  const time = new Intl.DateTimeFormat(locale, {
    hour: display.time_format === "24h" ? "2-digit" : "numeric",
    minute: "2-digit",
    hourCycle:
      display.time_format === "24h" ? "h23" : display.time_format === "12h" ? "h12" : undefined,
  }).format(date);
  return `${formattedDate} · ${time}`;
}

/**
 * One cell of a record, formatted for read-only display - `formatCellValue`, with
 * a link named by the records it points at, which only the record carries.
 */
export function recordCellText(
  column: ColumnDef,
  record: RecordRead,
  boolLabel: (value: boolean) => string,
  locale?: string,
  display?: TableDisplay,
): string {
  if (column.system)
    return formatCellValue(
      column,
      systemCellValue(column.system, record),
      boolLabel,
      locale,
      display,
    );
  if (column.type === "link") {
    return (record.links?.[column.id] ?? []).map((linked) => linked.label).join(", ");
  }
  return formatCellValue(column, record.values[column.id] ?? null, boolLabel, locale, display);
}
