/**
 * The columns a dataset file is imported with, and a template file that holds them.
 *
 * The same names, in the same order, as `COLUMNS` in
 * `backend/app/services/dataset_files.py`, which reads the file;
 * `backend/tests/test_dataset_import_columns.py` fails when the two differ.
 */
export const IMPORT_COLUMNS = [
  "input",
  "history",
  "reference_answer",
  "counter_example",
  "expected_tool_calls",
  "order_mode",
  "checks",
  "tags",
  "note",
] as const;

export type ImportColumn = (typeof IMPORT_COLUMNS)[number];

// i18n-exempt: the template's sample row is file content in the importer's own vocabulary, not console copy
const EXAMPLE: Record<ImportColumn, string> = {
  input: "How long does a refund take?",
  history: "",
  reference_answer: "A refund reaches your card within 5 working days.",
  counter_example: "Refunds take 30 days.",
  expected_tool_calls: "",
  order_mode: "",
  checks: '[{"type": "contains", "value": "5 working days"}]',
  tags: "refunds,billing",
  note: "Asked often in chat.",
};

function cell(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

/** A CSV with every column and one example case, which imports as it is. */
export function importTemplate(): Blob {
  const rows = [IMPORT_COLUMNS.join(","), IMPORT_COLUMNS.map((c) => cell(EXAMPLE[c])).join(",")];
  return new Blob([`${rows.join("\n")}\n`], { type: "text/csv" });
}
