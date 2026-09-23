/**
 * TypeScript mirror of the backend workflow + node-catalog contracts (#1786).
 *
 * These interfaces mirror, field for field, the Pydantic models the API serves:
 * - `app/schemas/workflow.py` — the registry and the node catalog.
 * - `app/workflows/graph/model.py` — the graph shape (nodes, edges, scopes).
 * - `app/workflows/contracts/io.py` — a binding and its source union.
 *
 * The wire is JSON, so every `UUID` arrives as a string and every Python
 * `tuple`/`frozenset` as an array. The names here are the JSON field names the
 * backend emits (snake_case), not camelCased, so a value can be handed to
 * `apiClient` unchanged.
 *
 * This module is the single import point for downstream editor code: the canvas,
 * palette, property panel, pickers, validation mirror, store and hooks all take
 * their types from here. Nothing here renders; nothing here fetches.
 */

/** A serialized UUID. An alias, so a signature reads as the contract does. */
export type Uuid = string;

/** JSON Schema as the catalog serves it, for building a form from a port/config. */
export type JsonSchema = Record<string, unknown>;

// Node catalog — `app/schemas/workflow.py`

/**
 * One port of a catalog entry — a connection point the canvas draws.
 *
 * `kind` decides handle placement directly; the canvas never infers direction
 * from a port id convention. `schema` is null for a control port with no
 * payload. The backend field is `schema` (aliased from `schema_`), so it is
 * `schema` on the wire and here.
 */
export interface Port {
  id: string;
  label: string;
  kind: "input" | "output";
  schema: JsonSchema | null;
}

/**
 * One registered node type, as the palette shows it and the property panel
 * builds a form from. Mirrors `NodeCatalogEntry`. No handler crosses the wire.
 */
export interface NodeDefinition {
  id: string;
  version: number;
  name: string;
  category: string;
  description: string;
  kind: "action" | "control" | "waiting";
  config_schema: JsonSchema | null;
  input_schema: JsonSchema | null;
  output_schema: JsonSchema | null;
  ports: Port[];
  effect_kind: "pure" | "read" | "write";
  retry_guarantee: "none" | "idempotent" | "at_least_once";
  scopes: string[];
}

/** Every registered node type — the palette's backing list. Mirrors `NodeCatalog`. */
export interface NodeCatalog {
  items: NodeDefinition[];
  total: number;
}

// Bindings — `app/workflows/contracts/io.py`

/** A reference to an uploaded file. Mirrors `FileRef`. */
export interface FileRef {
  kind: "file";
  file_id: Uuid;
  content_type: string;
  byte_size: number;
}

/**
 * A reference into one virtual table, optionally narrowed to some columns.
 * Mirrors `TableIORef`. `column_ids` null means "all live columns".
 */
export interface TableIORef {
  kind: "table";
  table_id: Uuid;
  column_ids: Uuid[] | null;
  schema_version: number;
}

/**
 * A reference to another node's output port, or a field within it. Mirrors
 * `NodeOutputRef`. `field_path` empty means "the whole port value".
 */
export interface NodeOutputRef {
  kind: "node_output";
  node_id: Uuid;
  port: string;
  field_path: string[];
}

/** A constant value, typed by whatever field it is bound to. Mirrors `LiteralValue`. */
export interface LiteralValue {
  kind: "literal";
  value: unknown;
}

/** What a target field's binding resolves to. Mirrors `BindingSource`, discriminated on `kind`. */
export type BindingSource = FileRef | TableIORef | NodeOutputRef | LiteralValue;

/**
 * One field of one node instance, bound to a source. Mirrors `Binding`.
 *
 * `target_field` is a plain string. For a leaf nested in an array-of-rows or a
 * nested object it carries a JSON-Pointer-style path — see `bindingFieldPath`
 * / `parseBindingFieldPath` below, the one place that convention is defined.
 */
export interface Binding {
  target_node_id: Uuid;
  target_field: string;
  source: BindingSource;
}

// Graph — `app/workflows/graph/model.py`

/** Where the editor draws a node. Never read by validation or execution. Mirrors `NodePosition`. */
export interface NodePosition {
  x: number;
  y: number;
}

/**
 * One node in the graph: which definition, pinned to which version, configured
 * how. Mirrors `NodeInstance`. `config` holds only literal, static settings —
 * a runtime value lives in `bindings`, never here.
 */
export interface NodeInstance {
  id: Uuid;
  definition_id: string;
  definition_version: number;
  config: Record<string, unknown>;
  layout: NodePosition;
}

/** One control-flow or data-flow connection between two node ports. Mirrors `Edge`. */
export interface WorkflowEdge {
  id: Uuid;
  source_node_id: Uuid;
  source_port: string;
  target_node_id: Uuid;
  target_port: string;
}

/**
 * A control node and the body it owns, as the server has computed it. Mirrors
 * `ScopeBoundary`.
 *
 * `body_node_ids` is **server-derived** from edge topology, never client-authored:
 * a draft save that implies a different membership than the server recomputes has
 * that implication overwritten, not honored. The editor reads this to filter the
 * scoped view; it never writes it.
 */
export interface ScopeBoundary {
  scope_node_id: Uuid;
  body_node_ids: Uuid[];
  entry_port: string;
  exit_node_id: Uuid;
  exit_port: string;
}

/**
 * One workflow graph — what a draft holds and what a published version freezes.
 * Mirrors `WorkflowGraph`. The lists are flat; nesting is expressed by `scopes`,
 * not by a recursive subgraph.
 */
export interface WorkflowGraph {
  entry_node_id: Uuid;
  nodes: NodeInstance[];
  edges: WorkflowEdge[];
  bindings: Binding[];
  scopes: ScopeBoundary[];
}

// Registry resource — `app/schemas/workflow.py`

/** The lifecycle states the list groups by, matching `Agent`'s. */
export type WorkflowStatus = "draft" | "published" | "archived";

/** A workflow as the list shows it. Mirrors `WorkflowRead`. */
export interface WorkflowRead {
  id: Uuid;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  visibility: string;
  owner_user_id: Uuid | null;
  current_version_id: Uuid | null;
  draft_revision: number;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * A workflow plus the graph currently being edited. Mirrors `WorkflowDetail`.
 *
 * `draft_graph` is null for a workflow nobody has ever edited — there is no
 * meaningful empty graph to report, only the absence of one.
 */
export interface WorkflowDetail extends WorkflowRead {
  draft_graph: WorkflowGraph | null;
}

/** A page of workflows. Mirrors `WorkflowList`. */
export interface WorkflowList {
  items: WorkflowRead[];
  total: number;
}

/** One published, immutable version. Mirrors `WorkflowVersionRead`. */
export interface WorkflowVersionRead {
  id: Uuid;
  version: number;
  note: string | null;
  published_by_user_id: Uuid | null;
  budget_limit: number | null;
  created_at: string | null;
}

/** Every published version, newest first. Mirrors `WorkflowVersionList`. */
export interface WorkflowVersionList {
  items: WorkflowVersionRead[];
}

/** Create a workflow. Mirrors `WorkflowCreate`. */
export interface WorkflowCreate {
  name: string;
  description?: string | null;
  visibility?: string;
}

/**
 * Replace the draft graph, gated on the revision the caller last read. Mirrors
 * `WorkflowDraftUpdate`. `graph` is a raw JSON object on the wire (the backend
 * parses and validates it after authorization), so the editor sends its working
 * `WorkflowGraph` here as-is.
 */
export interface WorkflowDraftUpdate {
  graph: WorkflowGraph;
  expected_revision: number;
}

/** Publish the current draft, gated on the same revision. Mirrors `WorkflowPublish`. */
export interface WorkflowPublish {
  note?: string | null;
  expected_revision: number;
}

// Centralized conventions the design flags as open (§ "Open questions for #1786")

/**
 * Build a `Binding.target_field` path from segments, JSON-Pointer style.
 *
 * A binding-aware leaf nested inside an array-of-rows or an object needs a path,
 * not a bare field name: `mappings[0].value` is `mappings/0/value`. This is the
 * one place the frontend encodes that path; the client-side validator and the
 * property panel both call it so a single convention reaches the wire. A numeric
 * index is stringified. `/` and `~` inside a segment are escaped per RFC 6901
 * (`~1` and `~0`) so a segment containing a slash cannot forge a boundary.
 */
export function bindingFieldPath(segments: ReadonlyArray<string | number>): string {
  return segments
    .map((segment) => String(segment).replace(/~/g, "~0").replace(/\//g, "~1"))
    .join("/");
}

/**
 * Split a `Binding.target_field` path back into its segments — the inverse of
 * `bindingFieldPath`. Escapes are decoded `~1`→`/` before `~0`→`~`, the RFC 6901
 * order, so an escaped tilde does not swallow the character after it.
 */
export function parseBindingFieldPath(path: string): string[] {
  if (path === "") return [];
  return path.split("/").map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
}

/** How many characters of a node id are enough to tell two same-named nodes apart. */
export const NODE_ID_SUFFIX_LENGTH = 6;

/**
 * The head of a node id, for disambiguating two nodes of the same definition.
 *
 * `NodeInstance` has no per-instance label in #1786's model, so the canvas shows
 * the catalog's static name and this suffix beside it. Centralized so every
 * surface derives the same suffix from the same id.
 */
export function shortNodeId(nodeId: Uuid): string {
  return nodeId.slice(0, NODE_ID_SUFFIX_LENGTH);
}

/**
 * The name to show for a node instance: the catalog definition's name, suffixed
 * with a short id when a disambiguator is asked for.
 *
 * The separator is not copy — it is a mid-dot joining a name and an id fragment,
 * the same shape `collection-picker` uses to disambiguate same-named rows — so it
 * needs no translation. A caller that has resolved the definition passes its
 * `name`; one that has not passes a fallback (the definition id).
 */
export function nodeDisplayName(
  definitionName: string,
  nodeId: Uuid,
  disambiguate = false,
): string {
  return disambiguate ? `${definitionName} · ${shortNodeId(nodeId)}` : definitionName;
}
