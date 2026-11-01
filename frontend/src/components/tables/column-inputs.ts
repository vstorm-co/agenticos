import type { ColumnDef, ColumnInput } from "@/types/tables";

/** The whole column list a schema change submits, every column as the table has it now. */
export function currentColumns(columns: ColumnDef[]): ColumnInput[] {
  return columns.map((column) => ({
    id: column.id,
    label: column.label,
    type: column.type,
    nullable: column.nullable,
    default: column.default,
    ...(column.document_templates !== undefined
      ? { document_templates: column.document_templates }
      : {}),
    ...(column.default_template_id !== undefined
      ? { default_template_id: column.default_template_id }
      : {}),
    options: column.options.map((option) => ({ ...option })),
    archived: column.archived,
    // What a link, lookup or rollup names goes back with every change: the
    // service refuses one sent without it.
    link_table_id: column.link_table_id ?? null,
    link_column_id: column.link_column_id ?? null,
    target_column_id: column.target_column_id ?? null,
    aggregate: column.aggregate ?? null,
    formula: column.formula ?? null,
  }));
}
