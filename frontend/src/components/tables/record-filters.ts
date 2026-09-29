import type { ColumnDef, ColumnTypeName, RecordFilter } from "@/types/tables";

/**
 * An operator as the filter bar offers it. `is_null` is one operator on the
 * wire with a boolean operand; a person picks "is empty" or "is not empty".
 */
export type FilterChoice =
  | "eq"
  | "ne"
  | "lt"
  | "lte"
  | "gt"
  | "gte"
  | "contains"
  | "starts_with"
  | "in"
  | "empty"
  | "not_empty";

const TEXTUAL: FilterChoice[] = ["contains", "eq", "ne", "starts_with", "empty", "not_empty"];
const ORDERED: FilterChoice[] = ["eq", "ne", "lt", "lte", "gt", "gte", "empty", "not_empty"];

// The service's operators per column type (`virtual_tables/types.py`), in the
// order a person reaches for them; `in` on text or numbers is left to the API.
const CHOICES: Record<ColumnTypeName, FilterChoice[]> = {
  text: TEXTUAL,
  long_text: TEXTUAL,
  number: ORDERED,
  integer: ORDERED,
  date: ORDERED,
  datetime: ORDERED,
  boolean: ["eq", "empty", "not_empty"],
  single_select: ["eq", "ne", "in", "empty", "not_empty"],
  multi_select: ["contains", "empty", "not_empty"],
};

export function choicesFor(column: ColumnDef): FilterChoice[] {
  return CHOICES[column.type];
}

export function choiceOf(filter: RecordFilter): FilterChoice {
  if (filter.op === "is_null") return filter.value === false ? "not_empty" : "empty";
  return filter.op;
}

/** A condition on `column`, as a fresh row starts: its first operator, no operand yet. */
export function newFilter(column: ColumnDef): RecordFilter {
  // Seeded without an operand, so the first operator starts from a fresh one.
  // Every type offers at least "is empty", so there is always a first.
  const first = choicesFor(column)[0] as FilterChoice;
  return withChoice({ column_id: column.id, op: "is_null" }, column, first);
}

/**
 * `filter` with operator `choice`. The operand stays when it still fits - a
 * value stays a value, a list stays a list - and is cleared when it does not.
 */
export function withChoice(
  filter: RecordFilter,
  column: ColumnDef,
  choice: FilterChoice,
): RecordFilter {
  if (choice === "empty" || choice === "not_empty") {
    return { column_id: filter.column_id, op: "is_null", value: choice === "empty" };
  }
  const wasList = filter.op === "in";
  const wasOperand = filter.op !== "is_null";
  const keeps = wasOperand && wasList === (choice === "in");
  const fresh = column.type === "boolean" ? true : null;
  return { column_id: filter.column_id, op: choice, value: keeps ? (filter.value ?? null) : fresh };
}

/** Whether a condition says enough to send: a half-written row narrows nothing yet. */
export function isComplete(filter: RecordFilter): boolean {
  const value = filter.value;
  if (filter.op === "is_null") return typeof value === "boolean";
  if (filter.op === "in") return Array.isArray(value) && value.length > 0;
  return value !== null && value !== undefined && value !== "";
}
