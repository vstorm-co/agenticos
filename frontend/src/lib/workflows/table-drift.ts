/**
 * Table references in a workflow draft whose table's schema has moved on.
 *
 * The backend refuses a run or a publish while any `TableIORef` names an older
 * `schema_version` than its table's (`table_ref_problems`), even when nothing the
 * step reads changed. The editor settles that itself where it is safe - every
 * column the reference reads still exists with the same type - and leaves the
 * rest for the author, as a problem on the step.
 */

import type { ColumnDef, SchemaVersionRead, TableRead } from "@/types/tables";
import type { TableIORef, Uuid, WorkflowGraph } from "./types";

/** Where in the graph a table reference sits: a step's `table` config or a binding. */
export type TableRefSite = { nodeId: Uuid; binding: null } | { nodeId: Uuid; binding: number };

export interface TableRefAt {
  site: TableRefSite;
  ref: TableIORef;
}

/** A reference that cannot be moved onto the current schema without the author. */
export interface TableDrift {
  nodeId: Uuid;
  /** The binding's target field, or null for the step's own `table`. */
  field: string | null;
  site: TableRefSite;
  /** The reference on the current schema, should the author accept it. */
  rebound: TableIORef;
}

function isTableRef(value: unknown): value is TableIORef {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { kind?: unknown }).kind === "table" &&
    typeof (value as { table_id?: unknown }).table_id === "string" &&
    typeof (value as { schema_version?: unknown }).schema_version === "number"
  );
}

/** Every table reference the graph holds: a step's `table`, and table-sourced bindings. */
export function graphTableRefs(graph: WorkflowGraph): TableRefAt[] {
  const refs: TableRefAt[] = [];
  for (const node of graph.nodes) {
    const table = (node.config as Record<string, unknown>).table;
    if (isTableRef(table)) refs.push({ site: { nodeId: node.id, binding: null }, ref: table });
  }
  graph.bindings.forEach((binding, index) => {
    if (binding.source.kind === "table") {
      refs.push({ site: { nodeId: binding.target_node_id, binding: index }, ref: binding.source });
    }
  });
  return refs;
}

/** The table's live columns, the ones a reference can read. */
export function liveColumns(table: TableRead): ColumnDef[] {
  return table.columns.filter((column) => !column.archived);
}

/**
 * The same reference moved onto the table's current schema, keeping its column
 * choice: every chosen column the schema still offers stays chosen. None left
 * falls back to all columns, as a fresh bind does.
 */
export function rebindRef(ref: TableIORef, version: number, live: ColumnDef[]): TableIORef {
  const liveIds = new Set(live.map((column) => column.id));
  const kept = ref.column_ids?.filter((id) => liveIds.has(id)) ?? [];
  return { ...ref, schema_version: version, column_ids: kept.length > 0 ? kept : null };
}

/**
 * Whether a stale reference can be moved onto the current schema unasked: every
 * column it read at its bound version - the chosen ones, or all live ones for an
 * all-columns reference - is still live now, with the same type. A column added
 * since is fine; one removed or retyped could break what reads the step.
 */
export function safeToRebind(
  ref: TableIORef,
  table: TableRead,
  versions: SchemaVersionRead[],
): boolean {
  const bound = versions.find((version) => version.version === ref.schema_version);
  if (!bound) return false;
  const now = new Map(liveColumns(table).map((column) => [column.id, column]));
  const read = bound.columns.filter(
    (column) => !column.archived && (ref.column_ids === null || ref.column_ids.includes(column.id)),
  );
  return read.every((column) => now.get(column.id)?.type === column.type);
}

/** The graph with each listed site's reference replaced. */
export function withRebound(
  graph: WorkflowGraph,
  updates: { site: TableRefSite; ref: TableIORef }[],
): WorkflowGraph {
  const nodes = new Map<Uuid, TableIORef>();
  const bindings = new Map<number, TableIORef>();
  for (const { site, ref } of updates) {
    if (site.binding === null) nodes.set(site.nodeId, ref);
    else bindings.set(site.binding, ref);
  }
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const ref = nodes.get(node.id);
      return ref ? { ...node, config: { ...node.config, table: ref } } : node;
    }),
    bindings: graph.bindings.map((binding, index) => {
      const ref = bindings.get(index);
      return ref ? { ...binding, source: ref } : binding;
    }),
  };
}

/**
 * Whether a refusal's field is a table reference: a step's own `table`, or a
 * binding (`table_ref_problems` scopes a table-sourced one to `bindings.<index>`).
 * Seeing one means the editor's copy of the tables is older than the server's.
 */
export function isTableRefusalField(field: string): boolean {
  return /^nodes\.[^.]+\.config\.table$/.test(field) || /^bindings\.\d+$/.test(field);
}

/** Steps that write a record's values, one binding per column (`values/<column id>`). */
const RECORD_WRITERS = new Set([
  "table.record.create",
  "table.record.update",
  "table.record.upsert",
]);

/** A binding the editor drops: its step and field. */
export interface BindingAt {
  nodeId: Uuid;
  field: string;
}

/**
 * Record values bound to a column the step's table no longer has live - one
 * archived or deleted since. The step's form stops showing such a field, so it
 * cannot be removed by hand, yet every run sends it and fails with
 * `UNKNOWN_COLUMN`. `live` maps a table id to its live column ids, for the
 * tables whose reference is on the current schema; other steps are skipped.
 */
export function orphanValueBindings(
  graph: WorkflowGraph,
  live: ReadonlyMap<string, ReadonlySet<string>>,
): BindingAt[] {
  const tables = new Map<Uuid, string>();
  for (const node of graph.nodes) {
    const table = (node.config as Record<string, unknown>).table;
    if (RECORD_WRITERS.has(node.definition_id) && isTableRef(table))
      tables.set(node.id, table.table_id);
  }
  return graph.bindings.flatMap((binding) => {
    const tableId = tables.get(binding.target_node_id);
    const columns = tableId === undefined ? undefined : live.get(tableId);
    const match = /^values\/([^/]+)$/.exec(binding.target_field);
    if (!columns || !match || columns.has(match[1]!)) return [];
    return [{ nodeId: binding.target_node_id, field: binding.target_field }];
  });
}

/** The ids of the tables a record-writing step reads, for `orphanValueBindings`. */
export function recordWriterTables(graph: WorkflowGraph): { tableId: string; version: number }[] {
  return graph.nodes.flatMap((node) => {
    const table = (node.config as Record<string, unknown>).table;
    return RECORD_WRITERS.has(node.definition_id) &&
      isTableRef(table) &&
      graph.bindings.some(
        (binding) =>
          binding.target_node_id === node.id && binding.target_field.startsWith("values/"),
      )
      ? [{ tableId: table.table_id, version: table.schema_version }]
      : [];
  });
}
