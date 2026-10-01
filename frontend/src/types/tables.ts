/**
 * Types for Virtual Tables, mirroring `backend/app/schemas/virtual_table.py`
 * and `backend/app/schemas/table_view.py`.
 */

/** Every column type, in the order a column type picker lists them. */
export const COLUMN_TYPES = [
  "text",
  "long_text",
  "number",
  "integer",
  "boolean",
  "date",
  "datetime",
  "single_select",
  "multi_select",
] as const;

export type ColumnTypeName = (typeof COLUMN_TYPES)[number];

/**
 * What a column of each type may become - every value is rewritten to it, and a
 * change some value does not survive is refused. Mirrors `CONVERSIONS` in
 * `backend/app/services/virtual_tables/conversions.py`.
 */
export const COLUMN_CONVERSIONS: Record<ColumnTypeName, readonly ColumnTypeName[]> = {
  text: ["long_text", "number", "integer", "boolean", "date", "datetime", "single_select"],
  long_text: ["text", "number", "integer", "boolean", "date", "datetime"],
  number: ["text", "long_text", "integer"],
  integer: ["text", "long_text", "number"],
  boolean: ["text", "long_text"],
  date: ["text", "long_text", "datetime"],
  datetime: ["text", "long_text"],
  single_select: ["text", "long_text", "multi_select"],
  multi_select: ["text", "long_text", "single_select"],
};

export type FilterOp =
  "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "contains" | "starts_with" | "in" | "is_null";

type SortDirection = "asc" | "desc";

export type TableVisibility = "private" | "team" | "org";

/** What one cell can hold. A select column stores option ids, a multi-select a list of them. */
export type CellValue = string | number | boolean | string[] | null;

type FilterValue = CellValue | CellValue[];

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

/** A table as the catalog lists it: how much it holds. Mirrors `TableListItem`. */
export interface TableListItem extends TableSummary {
  record_count: number;
  /** Live columns of its current schema. */
  column_count: number;
}

export interface TableList {
  items: TableListItem[];
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
  /** Text to find in any live text column or select option label, ignoring case. */
  search?: string | null;
  sort?: RecordSort;
  skip?: number;
  limit?: number;
}

/** What a count narrows by: a query's filters and search, without its order or page. */
export type RecordCountQuery = Pick<RecordQuery, "filters" | "search">;

export interface RecordCount {
  /** How many records match, up to the cap. */
  count: number;
  /** Whether more match than the cap, so `count` is a floor. */
  capped: boolean;
}

export interface RecordBatchFailure {
  /** The record's position in the batch, from 0. */
  index: number;
  code: string;
  message: string;
  details: Record<string, unknown> | null;
}

export interface RecordBatchResult {
  created: number;
  failed: RecordBatchFailure[];
}

export interface RecordExportQuery extends RecordCountQuery {
  sort?: RecordSort;
  /** The live columns to write, in order; `null` writes every live one. */
  columns?: string[] | null;
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
  search: string | null;
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
  /** Whether this caller may rename, reconfigure or reshare this view - needs `tables:edit` on the table. */
  can_manage: boolean;
  /** Whether this caller may delete this view - its owner, even without edit access to the table. */
  can_delete: boolean;
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
  /**
   * A complete config, never a patch: the backend replaces the whole stored blob
   * when this is sent, filling any field the caller left out with its own default
   * rather than keeping the view's current value - so `{ sort }` alone would
   * silently reset the view's filters, visible columns and grouping. A caller that
   * wants to change one part of a view's config must merge it with the view's
   * current `config` first.
   */
  config?: TableViewConfig;
}

/** An empty, unfiltered config - the default a new view starts from. */
export function emptyViewConfig(): TableViewConfig {
  return {
    filters: [],
    search: null,
    sort: { by: "created_at", direction: "asc" },
    visible_columns: null,
    group_by: null,
  };
}

/**
 * A workflow a table runs when a record is added - its "New table record"
 * trigger node, switched on by publishing it. Mirrors `TableTriggerRead`. It runs
 * the version that switched it on, as the member who published that version.
 */
export interface TableTriggerRead {
  id: string;
  table_id: string;
  workflow_id: string;
  workflow_name: string;
  workflow_version_id: string;
  version_number: number;
  node_instance_id: string;
  revision: number;
  filters: RecordFilter[];
  execution_principal_user_id: string | null;
  is_active: boolean;
  activated_at: string | null;
  created_at: string | null;
}

export interface TableTriggerList {
  items: TableTriggerRead[];
}

/** Pause or resume it. Mirrors `TableTriggerUpdate`. */
export interface TableTriggerUpdate {
  is_active: boolean;
}

export type AdmissionStatus = "queued" | "filtered" | "blocked" | "failed";

/** What one added record led to, for one trigger. Mirrors `TableTriggerAdmissionRead`. */
export interface TableTriggerAdmission {
  id: string;
  trigger_revision: number;
  status: AdmissionStatus;
  reason: string | null;
  workflow_run_id: string | null;
  created_at: string;
}

export interface TableTriggerAdmissionList {
  items: TableTriggerAdmission[];
  total: number;
}
