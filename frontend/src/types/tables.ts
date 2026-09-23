/**
 * Types for Virtual Tables, mirroring `backend/app/schemas/virtual_table.py`
 * and `backend/app/schemas/table_view.py`.
 */

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

export type FilterOp =
  "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "contains" | "starts_with" | "in" | "is_null";

export type SortDirection = "asc" | "desc";

export type TableVisibility = "private" | "team" | "org";

/** What one cell can hold. A select column stores option ids, a multi-select a list of them. */
export type CellValue = string | number | boolean | string[] | null;

export type FilterValue = CellValue | CellValue[];

export interface OptionDef {
  id: string;
  label: string;
  archived: boolean;
}

export interface ColumnDef {
  id: string;
  label: string;
  type: ColumnTypeName;
  nullable: boolean;
  default: CellValue;
  options: OptionDef[];
  archived: boolean;
}

/** A column as the client submits it on a schema change - no id for a new one. */
export interface ColumnInput {
  id?: string;
  label: string;
  type: ColumnTypeName;
  nullable?: boolean;
  default?: CellValue;
  options?: { id?: string; label: string; archived?: boolean }[];
  archived?: boolean;
}

export interface TableSummary {
  id: string;
  name: string;
  description: string | null;
  visibility: TableVisibility;
  owner_user_id: string | null;
  schema_version: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string | null;
  /**
   * Whether this caller may edit this table - role scope or an explicit grant,
   * resolved server-side so a catalog row never shows a control the write
   * would refuse. Hides controls; the backend re-checks on every write.
   */
  can_edit: boolean;
}

export interface TableRead extends TableSummary {
  columns: ColumnDef[];
}

export interface TableList {
  items: TableSummary[];
  total: number;
}

export interface TableCreate {
  name: string;
  description?: string | null;
  visibility?: TableVisibility;
  columns?: ColumnInput[];
}

export interface TableUpdate {
  name?: string;
  description?: string | null;
  visibility?: TableVisibility;
}

export interface SchemaUpdate {
  expected_version: number;
  columns: ColumnInput[];
}

export interface RecordFilter {
  column_id: string;
  op: FilterOp;
  value?: FilterValue;
}

export interface RecordSort {
  by: string;
  direction: SortDirection;
}

export interface RecordQuery {
  filters?: RecordFilter[];
  sort?: RecordSort;
  skip?: number;
  limit?: number;
}

export interface RecordRead {
  id: string;
  table_id: string;
  external_id: string | null;
  schema_version: number;
  values: Record<string, CellValue>;
  revision: number;
  created_at: string;
  updated_at?: string | null;
}

export interface RecordList {
  items: RecordRead[];
  skip: number;
  limit: number;
  has_more: boolean;
}

export interface RecordCreate {
  external_id?: string | null;
  values: Record<string, CellValue>;
}

export interface RecordUpdate {
  expected_revision: number;
  values: Record<string, CellValue>;
}

export type ViewKind = "table" | "kanban" | "list";
export type ViewVisibility = "private" | "shared";

export interface TableViewConfig {
  filters: RecordFilter[];
  sort: RecordSort;
  /** `null` means every live column. */
  visible_columns: string[] | null;
  /** A live `single_select` column - required for a kanban view. */
  group_by: string | null;
}

export interface TableViewRead {
  id: string;
  table_id: string;
  owner_user_id: string;
  name: string;
  kind: ViewKind;
  visibility: ViewVisibility;
  config: TableViewConfig;
  /** Whether this caller may rename, reconfigure or delete this view. */
  can_manage: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface TableViewList {
  items: TableViewRead[];
  total: number;
}

export interface TableViewCreate {
  name: string;
  kind: ViewKind;
  visibility?: ViewVisibility;
  config?: Partial<TableViewConfig>;
}

export interface TableViewUpdate {
  name?: string;
  visibility?: ViewVisibility;
  config?: Partial<TableViewConfig>;
}

/** An empty, unfiltered config - the default a new view starts from. */
export function emptyViewConfig(): TableViewConfig {
  return {
    filters: [],
    sort: { by: "created_at", direction: "asc" },
    visible_columns: null,
    group_by: null,
  };
}
