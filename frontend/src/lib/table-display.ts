import type { ColumnDef, TableDisplay } from "@/types/tables";

export const DEFAULT_TABLE_DISPLAY: TableDisplay = {
  column_order: [],
  hidden_system_columns: [],
  wrap_text: false,
  date_format: "locale",
  time_format: "locale",
};

export function viewColumnKey(column: ColumnDef): string {
  return column.system ?? column.id;
}

/** Unknown/archived IDs are ignored; newly added columns follow the saved ones. */
export function orderedTableColumns(columns: ColumnDef[], order: readonly string[]): ColumnDef[] {
  const ranks = new Map(order.map((key, index) => [key, index]));
  return columns.toSorted(
    (left, right) =>
      (ranks.get(viewColumnKey(left)) ?? order.length) -
      (ranks.get(viewColumnKey(right)) ?? order.length),
  );
}
