import { columnLabelFold } from "./column-label-fold";
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
  /** Dependent filters, sort or write bindings must be edited before rebinding. */
  requiresReview?: boolean;
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

/** Every table reference consumed by an enabled step: a step's `table`, and table-sourced bindings. */
export function graphTableRefs(graph: WorkflowGraph): TableRefAt[] {
  const refs: TableRefAt[] = [];
  const disabled = new Set(graph.nodes.filter((node) => node.disabled).map((node) => node.id));
  for (const node of graph.nodes) {
    if (node.disabled) continue;
    const table = (node.config as Record<string, unknown>).table;
    if (isTableRef(table)) refs.push({ site: { nodeId: node.id, binding: null }, ref: table });
  }
  graph.bindings.forEach((binding, index) => {
    if (!disabled.has(binding.target_node_id) && binding.source.kind === "table") {
      refs.push({ site: { nodeId: binding.target_node_id, binding: index }, ref: binding.source });
    }
  });
  return refs;
}

/** Additional column dependencies; null means a whole-record input needs review. */
export function nodeTableColumns(
  graph: WorkflowGraph,
  site: TableRefSite,
  schema?: { before: readonly ColumnDef[]; after: readonly ColumnDef[] },
): string[] | null {
  if (site.binding !== null) return [];
  const node = graph.nodes.find((entry) => entry.id === site.nodeId);
  if (!node || node.disabled) return [];
  const config = node.config;
  const columns = new Set<string>();
  if (Array.isArray(config.filters)) {
    for (const value of config.filters) {
      const filter: unknown = value;
      if (
        typeof filter === "object" &&
        filter !== null &&
        "column_id" in filter &&
        typeof filter.column_id === "string"
      ) {
        columns.add(filter.column_id);
      }
    }
  }
  const sort = config.sort;
  if (
    typeof sort === "object" &&
    sort !== null &&
    "by" in sort &&
    typeof sort.by === "string" &&
    sort.by !== "created_at" &&
    sort.by !== "updated_at"
  ) {
    columns.add(sort.by);
  }
  if (RECORD_WRITERS.has(node.definition_id)) {
    for (const binding of graph.bindings) {
      if (binding.target_node_id === node.id && binding.target_field === "values") return null;
      const match = /^values\/([^/]+)$/.exec(binding.target_field);
      if (binding.target_node_id === node.id && match) {
        const key = match[1]!.replace(/~1/g, "/").replace(/~0/g, "~");
        if (schema) {
          const before = resolveColumnKey(schema.before, key);
          if (before === null || before !== resolveColumnKey(schema.after, key)) return null;
          columns.add(before);
        } else {
          columns.add(key);
        }
      }
    }
  }
  return [...columns];
}

/** Match the server's ID precedence and unique, live, caseless label lookup. */
function resolveColumnKey(columns: readonly ColumnDef[], key: string): string | null {
  const live = columns.filter((column) => !column.archived);
  const id = live.find((column) => column.id === key);
  if (id) return id.id;
  const folded = columnLabelFold(key);
  const matches = live.filter((column) => columnLabelFold(column.label) === folded);
  return matches.length === 1 ? matches[0]!.id : null;
}

/** The table's live columns, the ones a reference can read. */
export function liveColumns(table: TableRead): ColumnDef[] {
  return table.columns.filter((column) => !column.archived);
}

/**
 * The same reference moved onto the table's current schema, keeping its column
 * choice: every chosen column the schema still offers stays chosen, and an
 * all-columns reference stays one.
 */
export function rebindRef(ref: TableIORef, version: number, live: ColumnDef[]): TableIORef {
  const liveIds = new Set(live.map((column) => column.id));
  // An explicit choice stays explicit, even emptied: `null` would widen it to
  // every live column.
  const column_ids =
    ref.column_ids === null ? null : ref.column_ids.filter((id) => liveIds.has(id));
  return { ...ref, schema_version: version, column_ids };
}

/**
 * Whether a stale reference can be moved onto the current schema unasked: every
 * column it read at its bound version - the chosen ones, or all live ones for an
 * all-columns reference - is still live now, with the same type and `revision`.
 * A column added since is fine; one removed, retyped or redefined (a formula, a
 * lookup, its options) changes what the step reads, so the author decides.
 */
export function safeToRebind(
  ref: TableIORef,
  table: TableRead,
  versions: SchemaVersionRead[],
  additionalColumns: readonly string[] | null = [],
): boolean {
  // A whole-record input may name columns or labels only known at runtime.
  if (additionalColumns === null) return false;
  const bound = versions.find((version) => version.version === ref.schema_version);
  if (!bound) return false;
  const now = new Map(liveColumns(table).map((column) => [column.id, column]));
  const previous = new Map(
    bound.columns.filter((column) => !column.archived).map((column) => [column.id, column]),
  );
  const read = new Set([...(ref.column_ids ?? previous.keys()), ...additionalColumns]);
  return [...read].every((id) => {
    const column = previous.get(id);
    const current = now.get(id);
    return (
      column !== undefined &&
      current !== undefined &&
      current.type === column.type &&
      (current.revision ?? 0) === (column.revision ?? 0)
    );
  });
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
 * binding whose source is a table - `table_ref_problems` scopes that one to
 * `bindings.<index>`, which other binding problems share. Seeing one means the
 * editor's copy of the tables is older than the server's.
 */
export function isTableRefusalField(field: string, graph: WorkflowGraph | null): boolean {
  if (/^nodes\.[^.]+\.config\.table$/.test(field)) return true;
  const binding = /^bindings\.(\d+)$/.exec(field);
  return binding !== null && graph?.bindings[Number(binding[1])]?.source.kind === "table";
}

/** Steps that write record values, keyed by column id or label. */
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
 * `UNKNOWN_COLUMN`. `live` maps a table id to its current schema version and
 * live column ids and labels; a step whose reference names another version is skipped.
 */
export function orphanValueBindings(
  graph: WorkflowGraph,
  live: ReadonlyMap<
    string,
    { version: number; columns: readonly Pick<ColumnDef, "id" | "label">[] }
  >,
): BindingAt[] {
  // Per step, and only one already on the version the live columns belong to: a
  // stale writer of the same table is the author's to update, bindings and all.
  const columnsOf = new Map<Uuid, { ids: ReadonlySet<string>; labels: ReadonlySet<string> }>();
  for (const node of graph.nodes) {
    if (node.disabled) continue;
    const table = (node.config as Record<string, unknown>).table;
    if (!RECORD_WRITERS.has(node.definition_id) || !isTableRef(table)) continue;
    const current = live.get(table.table_id);
    if (current?.version === table.schema_version)
      columnsOf.set(node.id, {
        ids: new Set(current.columns.map((column) => column.id)),
        labels: new Set(current.columns.map((column) => columnLabelFold(column.label))),
      });
  }
  return graph.bindings.flatMap((binding) => {
    const columns = columnsOf.get(binding.target_node_id);
    const match = /^values\/([^/]+)$/.exec(binding.target_field);
    if (!columns || !match) return [];
    const key = match[1]!.replace(/~1/g, "/").replace(/~0/g, "~");
    // Ambiguous labels remain for server validation rather than losing the author's input.
    if (columns.ids.has(key) || columns.labels.has(columnLabelFold(key))) return [];
    return [{ nodeId: binding.target_node_id, field: binding.target_field }];
  });
}

/** The ids of the tables a record-writing step reads, for `orphanValueBindings`. */
export function recordWriterTables(graph: WorkflowGraph): { tableId: string; version: number }[] {
  return graph.nodes.flatMap((node) => {
    const table = (node.config as Record<string, unknown>).table;
    return !node.disabled &&
      RECORD_WRITERS.has(node.definition_id) &&
      isTableRef(table) &&
      graph.bindings.some(
        (binding) =>
          binding.target_node_id === node.id && binding.target_field.startsWith("values/"),
      )
      ? [{ tableId: table.table_id, version: table.schema_version }]
      : [];
  });
}
