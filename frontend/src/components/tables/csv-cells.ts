import type { CellValue, ColumnDef } from "@/types/tables";

/** A CSV cell read as a column's value, or the reason it cannot be one. */
export type CsvCell = { value: CellValue } | { problem: CellProblem };

export type CellProblem = "number" | "integer" | "boolean" | "date" | "datetime" | "option";

const TRUE = new Set(["true", "yes", "y", "1"]);
const FALSE = new Set(["false", "no", "n", "0"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * One CSV cell as the value its column stores - the reverse of what an export
 * writes, so a file exported and imported again comes back as it was.
 *
 * An empty cell is no value, left for the column's default. A number may use a
 * decimal comma; a yes/no reads `true`/`false`, `yes`/`no` or `1`/`0`; a select
 * names its options by label or id, several separated by `;`. A leading `'` an
 * export added to keep a spreadsheet from reading a formula is taken off.
 */
export function readCell(column: ColumnDef, raw: string): CsvCell {
  const text = raw.startsWith("'") ? raw.slice(1) : raw;
  const trimmed = text.trim();
  if (trimmed === "") return { value: null };
  switch (column.type) {
    case "text":
    case "long_text":
      return { value: text };
    case "number":
    case "integer": {
      const number = Number(trimmed.replace(",", "."));
      if (!Number.isFinite(number)) return { problem: "number" };
      if (column.type === "integer" && !Number.isInteger(number)) return { problem: "integer" };
      return { value: number };
    }
    case "boolean": {
      const word = trimmed.toLowerCase();
      if (TRUE.has(word)) return { value: true };
      if (FALSE.has(word)) return { value: false };
      return { problem: "boolean" };
    }
    case "date":
      return ISO_DATE.test(trimmed) && !Number.isNaN(Date.parse(trimmed))
        ? { value: trimmed }
        : { problem: "date" };
    case "datetime": {
      const when = Date.parse(trimmed);
      return Number.isNaN(when) ? { problem: "datetime" } : { value: new Date(when).toISOString() };
    }
    case "single_select": {
      const option = optionFor(column, trimmed);
      return option === null ? { problem: "option" } : { value: option };
    }
    case "multi_select": {
      const ids = trimmed
        .split(";")
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) => optionFor(column, part));
      return ids.includes(null) ? { problem: "option" } : { value: ids as string[] };
    }
  }
}

/** A live option by its id or its label, ignoring case; `null` when the column has none such. */
function optionFor(column: ColumnDef, name: string): string | null {
  const needle = name.toLowerCase();
  const option = column.options.find(
    (candidate) =>
      !candidate.archived && (candidate.id === name || candidate.label.toLowerCase() === needle),
  );
  return option?.id ?? null;
}
