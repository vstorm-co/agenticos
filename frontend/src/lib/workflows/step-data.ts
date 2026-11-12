import { entryGraph, entryNodes } from "./triggers";
import { outputRefs, type Uuid, type WorkflowGraph, type WorkflowNodeRunRead } from "./types";

/** What one step did the last time a watched test run reached it. */
export interface StepData {
  /** What it handed on; null when it failed. */
  output: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
  runId: string;
}

/** How much data one step may have pinned, as compact UTF-8 JSON. Mirrors `MAX_PINNED_BYTES`. */
export const MAX_PINNED_BYTES = 64_000;

/** Rows a table view shows before saying how many more there are. */
export const SHOWN_ROWS = 50;
/** Columns a table view shows; the JSON view has the rest. */
const SHOWN_COLUMNS = 12;
/** Fields a schema view lists. */
const SHOWN_FIELDS = 200;
/** How far into nested objects a schema view goes. */
const SCHEMA_DEPTH = 4;

export function jsonBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

/** What one row did: its output once it succeeded, its error once it failed. */
function rowData(runId: string, row: WorkflowNodeRunRead): StepData | null {
  if (row.status === "succeeded" && row.output !== null) {
    return { output: row.output, error: null, runId };
  }
  if (row.status === "failed" && row.error !== null) {
    return { output: null, error: { code: row.error.code, message: row.error.message }, runId };
  }
  return null;
}

/**
 * What each step of a run did: its output once it succeeded, its error once it
 * failed. A step run once per loop item keeps its last item's - what a step
 * test pins for it.
 */
export function stepDataOf(runId: string, rows: WorkflowNodeRunRead[]): Record<Uuid, StepData> {
  const data: Record<Uuid, StepData> = {};
  for (const row of rows) {
    const done = rowData(runId, row);
    if (done !== null) data[row.node_instance_id] = done;
  }
  return data;
}

/** The loop iteration a row ran in, as its item index in each enclosing loop. */
export function iterationOf(row: WorkflowNodeRunRead): number[] {
  return row.scope_path.map((scope) => scope.index);
}

/** Where one step's data in one loop iteration is kept. */
function iterationKey(nodeId: Uuid, iteration: readonly number[]): string {
  return [nodeId, ...iteration].join("/");
}

/**
 * What each step of a run did in each loop iteration, for `stepDataAt`. A row
 * with no result yet - pending, running, cancelled - is kept empty, so its
 * iteration never shows another iteration's data.
 */
export function iterationDataOf(
  runId: string,
  rows: WorkflowNodeRunRead[],
): Record<string, StepData> {
  const data: Record<string, StepData> = {};
  for (const row of rows) {
    data[iterationKey(row.node_instance_id, iterationOf(row))] = rowData(runId, row) ?? {
      output: null,
      error: null,
      runId,
    };
  }
  return data;
}

/**
 * The steps a run took, in the order they started: a step that never started -
 * waiting its turn, skipped, cancelled first - is left out. The API lists rows
 * in the order they were recorded, which a loop's item step breaks: it is
 * recorded after the steps it started.
 */
export function stepsTaken(rows: WorkflowNodeRunRead[]): WorkflowNodeRunRead[] {
  const notStarted = new Set(["pending", "skipped", "cancelled"]);
  const at = (row: WorkflowNodeRunRead) => {
    const time = row.started_at ?? row.ended_at;
    return {
      row,
      millis: time === null ? Number.MAX_SAFE_INTEGER : Date.parse(time),
      // Date.parse drops the microseconds PostgreSQL keeps on a fast step.
      fraction: (time?.match(/\.(\d+)/)?.[1] ?? "").padEnd(6, "0"),
    };
  };
  return rows
    .filter((row) => row.started_at !== null || !notStarted.has(row.status))
    .map(at)
    .sort((a, b) => a.millis - b.millis || a.fraction.localeCompare(b.fraction))
    .map(({ row }) => row);
}

/**
 * What a step did as seen from one loop iteration: its row in that iteration -
 * empty while it has no result - or in the nearest enclosing one for a step
 * outside the loop, else its latest data. An empty iteration reads the latest
 * data.
 */
export function stepDataAt(
  stepData: Readonly<Record<Uuid, StepData>>,
  iterations: Readonly<Record<string, StepData>>,
  nodeId: Uuid,
  iteration: readonly number[],
): StepData | undefined {
  for (let depth = iteration.length; depth > 0; depth--) {
    const found = iterations[iterationKey(nodeId, iteration.slice(0, depth))];
    if (found !== undefined) return found;
  }
  return stepData[nodeId];
}

/** The steps one step reads from: those its fields are bound to, then those wired into it. */
export function sourcesOf(graph: WorkflowGraph, nodeId: Uuid): Uuid[] {
  const sources = new Set<Uuid>();
  for (const binding of graph.bindings) {
    if (binding.target_node_id !== nodeId) continue;
    for (const ref of outputRefs(binding.source)) sources.add(ref.node_id);
  }
  for (const edge of graph.edges) {
    if (edge.target_node_id === nodeId) sources.add(edge.source_node_id);
  }
  return graph.nodes.map((node) => node.id).filter((id) => sources.has(id));
}

/**
 * The steps a step's Input pane can show the data of, nearest first: every step
 * it may read from (`reachable` - those sure to have run before it), with any it
 * is wired from or already reads. The step just before it comes first; steps
 * as near are in the order the graph holds them.
 */
export function earlierSteps(
  graph: WorkflowGraph,
  nodeId: Uuid,
  reachable: ReadonlySet<Uuid>,
): Uuid[] {
  const steps = new Set([...reachable, ...sourcesOf(graph, nodeId)]);
  steps.delete(nodeId);
  // A step switched off does nothing, so it has nothing to show or to read.
  for (const node of graph.nodes) if (node.disabled === true) steps.delete(node.id);
  // How many connections back each step is, walking the wires upstream.
  const away = new Map<Uuid, number>([[nodeId, 0]]);
  const queue = [nodeId];
  for (let at = queue.shift(); at !== undefined; at = queue.shift()) {
    // Queued only once its distance is known.
    const next = (away.get(at) as number) + 1;
    for (const wire of graph.edges) {
      if (wire.target_node_id !== at || away.has(wire.source_node_id)) continue;
      away.set(wire.source_node_id, next);
      queue.push(wire.source_node_id);
    }
  }
  const order = graph.nodes.map((node) => node.id);
  const distance = (id: Uuid) => away.get(id) ?? Number.MAX_SAFE_INTEGER;
  return [...steps].sort(
    (a, b) => distance(a) - distance(b) || order.indexOf(a) - order.indexOf(b),
  );
}

/** Whether a step runs once per item of a loop - only the loop as a whole can be tested. */
export function isInsideALoop(graph: WorkflowGraph, nodeId: Uuid): boolean {
  return graph.scopes.some((scope) => scope.body_node_ids.includes(nodeId));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export interface DataTable {
  columns: string[];
  rows: Record<string, unknown>[];
  /**
   * Where each column sits in the data, for a column a later step can read -
   * null when the rows are a list's items, which no single path reaches.
   */
  paths: Record<string, string[]> | null;
}

/** A row with its nested objects spread into `parent.child` columns, two levels deep. */
function flatRow(
  row: Record<string, unknown>,
  paths: Record<string, string[]>,
  prefix: string[] = [],
): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    const path = [...prefix, key];
    if (isRecord(value) && path.length < 2) Object.assign(flat, flatRow(value, paths, path));
    else {
      const column = path.join(".");
      flat[column] = value;
      paths[column] = path;
    }
  }
  return flat;
}

/**
 * Columns in the order `order` names them - by their last segment, within the
 * columns sharing a prefix - the rest after, as they came.
 */
function ordered(columns: string[], order: readonly string[]): string[] {
  if (order.length === 0) return columns;
  const rank = (column: string) => {
    const at = order.indexOf(column.slice(column.lastIndexOf(".") + 1));
    return at < 0 ? order.length : at;
  };
  const groups = new Map<string, string[]>();
  for (const column of columns) {
    const prefix = column.slice(0, column.lastIndexOf(".") + 1);
    groups.set(prefix, [...(groups.get(prefix) ?? []), column]);
  }
  return [...groups.values()].flatMap((group) => group.sort((a, b) => rank(a) - rank(b)));
}

/**
 * Data as rows: the list of records it holds when it holds exactly one (a
 * table read, a search), otherwise the data itself as a single row - with
 * nested objects spread into columns either way.
 *
 * `order` names fields in the order to show them - a table's columns, which the
 * stored data cannot keep: Postgres orders an object's keys by their length.
 */
export function tableOf(value: Record<string, unknown>, order: readonly string[] = []): DataTable {
  const lists = Object.values(value).filter(
    (field): field is Record<string, unknown>[] =>
      Array.isArray(field) && field.length > 0 && field.every(isRecord),
  );
  const paths: Record<string, string[]> = {};
  const listed = lists.length === 1;
  const rows = (listed ? (lists[0] as Record<string, unknown>[]) : [value]).map((row) =>
    flatRow(row, paths),
  );
  const columns: string[] = [];
  for (const row of rows.slice(0, SHOWN_ROWS)) {
    for (const key of Object.keys(row)) {
      if (!columns.includes(key)) columns.push(key);
    }
  }
  return {
    columns: ordered(columns, order).slice(0, SHOWN_COLUMNS),
    rows,
    paths: listed ? null : paths,
  };
}

export interface SchemaField {
  path: string;
  type: string;
  /** The field's place in the data, for a later step to read; null inside a list's items. */
  segments: string[] | null;
}

/** A value's JSON type: `string`, `number`, `boolean`, `null`, `array` or `object`. */
export function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

/** Every field of the data, by path, with the type it holds - `items[].name` for a list's. */
export function schemaOf(value: Record<string, unknown>): SchemaField[] {
  const fields: SchemaField[] = [];
  const walk = (
    object: Record<string, unknown>,
    prefix: string,
    segments: string[] | null,
    depth: number,
  ) => {
    for (const [key, field] of Object.entries(object)) {
      if (fields.length >= SHOWN_FIELDS) return;
      const path = prefix === "" ? key : `${prefix}.${key}`;
      const here = segments === null ? null : [...segments, key];
      fields.push({ path, type: typeOf(field), segments: here });
      if (depth >= SCHEMA_DEPTH) continue;
      if (isRecord(field)) walk(field, path, here, depth + 1);
      else if (Array.isArray(field) && isRecord(field[0]))
        walk(field[0], `${path}[]`, null, depth + 1);
    }
  };
  walk(value, "", [], 1);
  return fields;
}

/** One cell of a table view: a value as short text. */
export function cellText(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  const text = JSON.stringify(value);
  return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** Every step with a path of connections into `nodeId`. */
export function ancestorsOf(graph: WorkflowGraph, nodeId: Uuid): Set<Uuid> {
  const found = new Set<Uuid>();
  const pending = [nodeId];
  while (pending.length > 0) {
    const current = pending.pop() as Uuid;
    for (const edge of graph.edges) {
      if (edge.target_node_id === current && !found.has(edge.source_node_id)) {
        found.add(edge.source_node_id);
        pending.push(edge.source_node_id);
      }
    }
  }
  return found;
}

/**
 * The start a step test of `nodeId` admits from, exactly as the backend's
 * `WorkflowExecutionService.start` picks it when no `entry_node_id` is named:
 * the first trigger root - the default entry, then any other trigger in graph
 * order - whose reachable branch contains the step, returned as that branch's
 * graph (its `entry_node_id` names the selected start). Null when no start
 * reaches the step.
 */
export function testEntryGraph(graph: WorkflowGraph, nodeId: Uuid): WorkflowGraph | null {
  for (const entry of entryNodes(graph)) {
    const branch = entryGraph(graph, entry.id);
    if (branch.nodes.some((node) => node.id === nodeId)) return branch;
  }
  return null;
}

/**
 * What a step test of `nodeId` pins for the steps before it: each one's output
 * from the test runs watched, when there is one.
 */
export function knownOutputs(
  graph: WorkflowGraph,
  nodeId: Uuid,
  stepData: Record<Uuid, StepData>,
): Record<Uuid, Record<string, unknown>> {
  const outputs: Record<Uuid, Record<string, unknown>> = {};
  for (const ancestor of ancestorsOf(graph, nodeId)) {
    const output = stepData[ancestor]?.output;
    if (output != null) outputs[ancestor] = output;
  }
  return outputs;
}

/** What the trigger handed on as the run's input last time, when that is known. */
export function knownInput(
  graph: WorkflowGraph,
  stepData: Record<Uuid, StepData>,
): Record<string, unknown> | null {
  const payload = stepData[graph.entry_node_id]?.output?.["payload"];
  return isRecord(payload) ? payload : null;
}
