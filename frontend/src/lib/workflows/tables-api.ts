/**
 * API client for the Virtual Tables routes the workflow editor reads (#1787).
 *
 * A workflow node that reads or writes a table pins it with a `TableIORef`
 * (`table_id`, `column_ids`, `schema_version`), chosen through the table +
 * column picker. That picker needs two things the registry endpoints answer:
 * the tables this member may see, and one table's *current* schema so a column
 * list is scoped to what exists now rather than what existed when the ref was
 * bound.
 *
 * The foundation did not add a tables module, so this is the single import point
 * for the pickers' table reads. Thin wrappers over `apiClient`, one per route in
 * `backend/app/api/routes/v1/virtual_tables.py`; the hooks in
 * `use-workflow-tables.ts` call these, components never do.
 *
 * The types mirror, field for field, the Pydantic models the API serves in
 * `app/schemas/virtual_table.py` — `TableSummary`, `TableRead`, `ColumnDef`.
 * The wire is JSON, so every `UUID` arrives as a string and every `datetime` as
 * an ISO string. Only the shapes the pickers read are mirrored here.
 */

import { apiClient } from "@/lib/api-client";
import type { Uuid } from "@/lib/workflows/types";

/** The column types a schema version may hold. Mirrors `ColumnTypeName`. */
export type ColumnTypeName =
  | "text"
  | "long_text"
  | "number"
  | "integer"
  | "boolean"
  | "date"
  | "datetime"
  | "single_select"
  | "multi_select";

/** One choice of a select column, as stored. Mirrors `OptionDef`. */
export interface ColumnOption {
  id: Uuid;
  label: string;
  archived: boolean;
}

/** What one cell can hold. Mirrors `CellValue`. */
export type CellValue = string | number | boolean | string[] | null;

/**
 * One column of a schema version. Mirrors `ColumnDef`. The `id` never changes,
 * whatever else does — which is what a `TableIORef.column_ids` entry names.
 */
export interface ColumnDef {
  id: Uuid;
  label: string;
  type: ColumnTypeName;
  nullable: boolean;
  default: CellValue;
  options: ColumnOption[];
  archived: boolean;
}

/** A table as the list shows it — no columns. Mirrors `TableSummary`. */
export interface TableSummary {
  id: Uuid;
  name: string;
  description: string | null;
  visibility: "private" | "team" | "org";
  owner_user_id: Uuid | null;
  schema_version: number;
  archived_at: string | null;
  created_at: string;
}

/** A table and the columns of its current schema. Mirrors `TableRead`. */
export interface TableRead extends TableSummary {
  columns: ColumnDef[];
  updated_at: string | null;
}

/** A page of tables. Mirrors `TableList`. */
export interface TableList {
  items: TableSummary[];
  total: number;
}

const ROOT = "/tables";

/**
 * The tables this member may see, by name.
 *
 * The picker filters and pages in the browser (`useListControls`), so it asks
 * for one large page rather than a query per keystroke. `include_archived` is
 * left at the server default: a workflow should not bind a fresh ref to an
 * archived table, and one already bound surfaces through the orphaned state.
 */
export async function listTables(params?: { skip?: number; limit?: number }): Promise<TableList> {
  const query =
    params && (params.skip !== undefined || params.limit !== undefined)
      ? {
          params: {
            skip: String(params.skip ?? 0),
            limit: String(params.limit ?? 50),
          },
        }
      : undefined;
  return apiClient.get<TableList>(ROOT, query);
}

/** One table and the columns of its *current* schema — what a column list is scoped to. */
export async function getTable(tableId: string): Promise<TableRead> {
  return apiClient.get<TableRead>(`${ROOT}/${tableId}`);
}
