import type { CellValue, ColumnDef, RecordFilter, RecordRead, RecordSort } from "@/types/tables";

/**
 * What the platform's table tools asked and answered, read out of a call.
 *
 * The `agenticos_*` table tools take column and option ids, because labels can
 * be renamed and ids cannot. That makes them right on the wire and unreadable in
 * a transcript: `{"column_id": "e30b…", "value": "8c6b…"}` is "Status is To be
 * analyzed" to anybody holding the schema. This module only parses; naming the
 * ids needs the table, which the component reads.
 */
export type TableTool = "query" | "get" | "exists" | "add" | "update" | "upsert" | "delete";

const TOOLS: Record<string, TableTool> = {
  agenticos_query_virtual_table: "query",
  agenticos_get_virtual_table_record: "get",
  agenticos_virtual_table_record_exists: "exists",
  agenticos_add_virtual_table_record: "add",
  agenticos_update_virtual_table_record: "update",
  agenticos_upsert_virtual_table_record: "upsert",
  agenticos_delete_virtual_table_record: "delete",
};

export interface TableCallQuery {
  filters: RecordFilter[];
  sort: RecordSort | null;
  search: string | null;
  limit: number | null;
}

export interface TableCall {
  tool: TableTool;
  tableId: string;
  recordId: string | null;
  externalId: string | null;
  query: TableCallQuery | null;
  values: Record<string, CellValue> | null;
}

type Json = Record<string, unknown>;

function object(value: unknown): Json | null {
  if (typeof value === "string") {
    try {
      return object(JSON.parse(value));
    } catch {
      return null;
    }
  }
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function readQuery(value: unknown): TableCallQuery {
  const query = object(value) ?? {};
  const filters = Array.isArray(query.filters)
    ? query.filters
        .map(object)
        .filter(
          (filter): filter is Json =>
            filter !== null &&
            typeof filter.column_id === "string" &&
            typeof filter.op === "string",
        )
        .map((filter) => filter as unknown as RecordFilter)
    : [];
  const sort = object(query.sort);
  return {
    filters,
    sort:
      sort !== null && typeof sort.by === "string"
        ? { by: sort.by, direction: sort.direction === "desc" ? "desc" : "asc" }
        : null,
    search: text(query.search),
    limit: typeof query.limit === "number" ? query.limit : null,
  };
}

function readValues(value: unknown): Record<string, CellValue> | null {
  const values = object(value);
  return values === null ? null : (values as Record<string, CellValue>);
}

/** The call as a table call, or null for any other tool or a call missing its table. */
export function parseTableCall(toolName: string, rawArgs: unknown): TableCall | null {
  const tool = TOOLS[toolName];
  const args = object(rawArgs);
  const tableId = text(args?.table_id);
  if (tool === undefined || args === null || tableId === null) return null;
  return {
    tool,
    tableId,
    recordId: text(args.record_id),
    externalId: text(args.external_id),
    query: tool === "query" ? readQuery(args.query) : null,
    values:
      tool === "add"
        ? readValues(args.values)
        : tool === "update"
          ? readValues(object(args.update)?.values)
          : tool === "upsert"
            ? readValues(object(args.record)?.values)
            : null,
  };
}

/** Whether `toolName` is one of the platform's table tools. */
export function isTableTool(toolName: string): boolean {
  return toolName in TOOLS;
}

export type TableCallAnswer =
  | { kind: "records"; records: RecordRead[]; hasMore: boolean }
  | { kind: "record"; record: RecordRead }
  | { kind: "exists"; exists: boolean }
  | { kind: "deleted" };

function isRecord(value: Json | null): value is Json & RecordRead {
  return value !== null && typeof value.id === "string" && object(value.values) !== null;
}

/** What the call answered, or null for an answer this module does not recognize. */
export function readTableAnswer(tool: TableTool, result: unknown): TableCallAnswer | null {
  const data = object(result);
  if (data === null || "error" in data) return null;
  if (tool === "query") {
    if (!Array.isArray(data.items)) return null;
    const records = data.items.map(object).filter(isRecord);
    return { kind: "records", records, hasMore: data.has_more === true };
  }
  if (tool === "exists") {
    return typeof data.exists === "boolean" ? { kind: "exists", exists: data.exists } : null;
  }
  if (tool === "delete") return data.deleted === true ? { kind: "deleted" } : null;
  return isRecord(data) ? { kind: "record", record: data } : null;
}

/** The column a person reads a record by: its first live text column. */
export function titleColumn(columns: readonly ColumnDef[]): ColumnDef | null {
  return (
    columns.find((column) => column.type === "text" && !column.archived && !column.system) ?? null
  );
}

export type SortKey = "createdAt" | "updatedAt";

/** A sort key as a column, or as the record field `created_at`/`updated_at` names. */
export function sortTarget(
  by: string,
  columns: readonly ColumnDef[],
): { column: ColumnDef } | { field: SortKey } | null {
  if (by === "created_at") return { field: "createdAt" };
  if (by === "updated_at") return { field: "updatedAt" };
  const column = columns.find((candidate) => candidate.id === by);
  return column === undefined ? null : { column };
}
