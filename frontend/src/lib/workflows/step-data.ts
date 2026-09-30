import type { Uuid, WorkflowGraph, WorkflowNodeRunRead } from "./types";

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

/**
 * What each step of a run did: its output once it succeeded, its error once it
 * failed. A step run once per loop item keeps its last item's.
 */
export function stepDataOf(runId: string, rows: WorkflowNodeRunRead[]): Record<Uuid, StepData> {
  const data: Record<Uuid, StepData> = {};
  for (const row of rows) {
    if (row.status === "succeeded" && row.output !== null) {
      data[row.node_instance_id] = { output: row.output, error: null, runId };
    } else if (row.status === "failed" && row.error !== null) {
      data[row.node_instance_id] = {
        output: null,
        error: { code: row.error.code, message: row.error.message },
        runId,
      };
    }
  }
  return data;
}

/** The steps one step reads from: those its fields are bound to, then those wired into it. */
export function sourcesOf(graph: WorkflowGraph, nodeId: Uuid): Uuid[] {
  const sources = new Set<Uuid>();
  for (const binding of graph.bindings) {
    if (binding.target_node_id === nodeId && binding.source.kind === "node_output") {
      sources.add(binding.source.node_id);
    }
  }
  for (const edge of graph.edges) {
    if (edge.target_node_id === nodeId) sources.add(edge.source_node_id);
  }
  return graph.nodes.map((node) => node.id).filter((id) => sources.has(id));
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
}

/** A row with its nested objects spread into `parent.child` columns, two levels deep. */
function flatRow(row: Record<string, unknown>, prefix = "", depth = 1): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    const column = prefix === "" ? key : `${prefix}.${key}`;
    if (isRecord(value) && depth < 2) Object.assign(flat, flatRow(value, column, depth + 1));
    else flat[column] = value;
  }
  return flat;
}

/**
 * Data as rows: the list of records it holds when it holds exactly one (a
 * table read, a search), otherwise the data itself as a single row - with
 * nested objects spread into columns either way.
 */
export function tableOf(value: Record<string, unknown>): DataTable {
  const lists = Object.values(value).filter(
    (field): field is Record<string, unknown>[] =>
      Array.isArray(field) && field.length > 0 && field.every(isRecord),
  );
  const rows = (lists.length === 1 ? (lists[0] as Record<string, unknown>[]) : [value]).map((row) =>
    flatRow(row),
  );
  const columns: string[] = [];
  for (const row of rows.slice(0, SHOWN_ROWS)) {
    for (const key of Object.keys(row)) {
      if (!columns.includes(key) && columns.length < SHOWN_COLUMNS) columns.push(key);
    }
  }
  return { columns, rows };
}

export interface SchemaField {
  path: string;
  type: string;
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

/** Every field of the data, by path, with the type it holds - `items[].name` for a list's. */
export function schemaOf(value: Record<string, unknown>): SchemaField[] {
  const fields: SchemaField[] = [];
  const walk = (object: Record<string, unknown>, prefix: string, depth: number) => {
    for (const [key, field] of Object.entries(object)) {
      if (fields.length >= SHOWN_FIELDS) return;
      const path = prefix === "" ? key : `${prefix}.${key}`;
      fields.push({ path, type: typeOf(field) });
      if (depth >= SCHEMA_DEPTH) continue;
      if (isRecord(field)) walk(field, path, depth + 1);
      else if (Array.isArray(field) && isRecord(field[0])) walk(field[0], `${path}[]`, depth + 1);
    }
  };
  walk(value, "", 1);
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
