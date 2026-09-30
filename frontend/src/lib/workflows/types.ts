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
  /** Whether the node exists only inside a `control.foreach` body (`loop.item`, `loop.yield`). */
  loop_body_only?: boolean;
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

/**
 * Text with values from earlier steps in it, rendered when the step runs. Mirrors
 * `TemplateValue`: `parts` alternate between text and references.
 */
export interface TemplateValue {
  kind: "template";
  parts: (string | NodeOutputRef)[];
}

/** What a target field's binding resolves to. Mirrors `BindingSource`, discriminated on `kind`. */
export type BindingSource = FileRef | TableIORef | NodeOutputRef | TemplateValue | LiteralValue;

/** Every other step's output a source reads: itself, a template's placeholders, or none. */
export function outputRefs(source: BindingSource): NodeOutputRef[] {
  if (source.kind === "node_output") return [source];
  if (source.kind === "template") {
    return source.parts.filter((part): part is NodeOutputRef => typeof part !== "string");
  }
  return [];
}

/** `source` with each step it reads renamed by `rename` - a paste's new ids, a replaced step. */
export function renameOutputRefs(
  source: BindingSource,
  rename: (nodeId: Uuid) => Uuid,
): BindingSource {
  if (source.kind === "node_output") return { ...source, node_id: rename(source.node_id) };
  if (source.kind === "template") {
    return {
      ...source,
      parts: source.parts.map((part) =>
        typeof part === "string" ? part : { ...part, node_id: rename(part.node_id) },
      ),
    };
  }
  return source;
}

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
  policy?: NodePolicy | null;
  layout: NodePosition;
  /** What the builder calls this step, unique in the graph; the catalog name when unset. */
  label?: string | null;
  /** A note on the step, shown on the canvas. */
  notes?: string | null;
  /** Switched off: skipped when the run reaches it, handing the run on. */
  disabled?: boolean;
  /** Data a test run hands on as this step's output instead of running it. */
  pinned_output?: Record<string, unknown> | null;
}

/** How many tries a failing step gets, and the wait between them. Mirrors `RetryPolicy`. */
export interface RetryPolicy {
  max_attempts: number;
  backoff?: "fixed" | "exponential";
  base_delay_seconds?: number;
  max_delay_seconds?: number;
}

/**
 * One node's time limit, retries and failure routing, beside its config. Mirrors
 * `NodePolicy`. `on_error: "route"` gives the node an `error` output port.
 */
export interface NodePolicy {
  timeout_seconds?: number | null;
  retry?: RetryPolicy | null;
  on_error?: "fail_run" | "route";
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
/** A note on the canvas beside the steps. Never run or validated. Mirrors `CanvasNote`. */
export interface CanvasNote {
  id: Uuid;
  /** Markdown. */
  text: string;
  layout: NodePosition;
  width?: number;
  height?: number;
}

export interface WorkflowGraph {
  entry_node_id: Uuid;
  nodes: NodeInstance[];
  edges: WorkflowEdge[];
  bindings: Binding[];
  scopes: ScopeBoundary[];
  /** Notes on the canvas; absent on a graph written before there were any. */
  notes?: CanvasNote[];
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
  /**
   * The trigger node the published version starts from - `core.input`,
   * `trigger.chat`, `trigger.webhook`, ... - or null when it starts from no
   * trigger (by hand) or was never published.
   */
  live_trigger: string | null;
  /** Labels the workflow is filed under, lower case, each once. */
  tags: string[];
  /**
   * Whether the published version's unattended trigger - a webhook, a schedule,
   * a new table record - is on; null when it has none.
   */
  trigger_active: boolean | null;
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
/** What a workflow is run with rather than what it does. Mirrors `WorkflowSettings`. */
/** A pin a workflow file does not carry. Mirrors `UnresolvedResource`. */
export interface UnresolvedResource {
  node_id: Uuid;
  /** The step's name, as the editor shows it. */
  step: string;
  field: string;
  kind: string;
}

/** A workflow as a file another deployment can import. Mirrors `WorkflowExport`. */
export interface WorkflowExport {
  format: "agenticos.workflow";
  format_version: 1;
  name: string;
  description: string | null;
  tags: string[];
  settings: WorkflowSettings;
  graph: WorkflowGraph | null;
  unresolved: UnresolvedResource[];
}

/** What an import made. Mirrors `WorkflowImported`. */
export interface WorkflowImported {
  workflow: WorkflowRead;
  unresolved: UnresolvedResource[];
}

export interface WorkflowSettings {
  /** An IANA timezone: the one a schedule's cron expression is read in. */
  timezone: string;
  /** The deadline a run gets when whatever starts it names none. */
  default_deadline_seconds: number | null;
  /** A published workflow starting from On failure of a workflow, started when a run fails. */
  error_workflow_id: Uuid | null;
  /** Days a run is kept after it ends; kept for good when null. */
  run_retention_days: number | null;
  keep_succeeded_runs: boolean;
}

/** The settings as the workflow holds them. Mirrors `StoredWorkflowSettings`. */
export interface StoredWorkflowSettings extends WorkflowSettings {
  /** The member the error workflow runs as: whoever chose it. */
  error_workflow_run_as: Uuid | null;
}

export interface WorkflowDetail extends WorkflowRead {
  draft_graph: WorkflowGraph | null;
  settings: StoredWorkflowSettings;
  /** Whether this caller may edit this workflow, resolved server-side; false once archived. */
  can_edit: boolean;
}

/** A page of workflows. Mirrors `WorkflowList`. */
export interface WorkflowList {
  items: WorkflowRead[];
  total: number;
}

/** One published, immutable version, as the lean history list shows it. Mirrors `WorkflowVersionRead`. */
export interface WorkflowVersionRead {
  id: Uuid;
  version: number;
  note: string | null;
  published_by_user_id: Uuid | null;
  budget_limit: number | null;
  created_at: string | null;
}

/**
 * The publish response: the new version, and the trigger it switched on.
 * Mirrors `WorkflowPublished`. `webhook_secret` is a webhook's signing secret,
 * only on the publish that first switched that webhook on.
 */
export interface WorkflowPublished extends WorkflowVersionRead {
  trigger: string | null;
  exposure: WorkflowExposureRead | null;
  webhook_secret: string | null;
}

/**
 * One version plus its frozen graph, fetched on demand to view it read-only.
 * Mirrors `WorkflowVersionDetail`. The list stays lean; the graph rides only here.
 */
export interface WorkflowVersionDetail extends WorkflowVersionRead {
  graph: WorkflowGraph;
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

/** Make a published version the draft again, gated like a draft write. Mirrors `WorkflowVersionRestore`. */
export interface WorkflowVersionRestore {
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
  label?: string | null,
): string {
  // A step the builder named is called that: names are unique in a graph.
  const own = label?.trim();
  if (own) return own;
  return disambiguate ? `${definitionName} · ${shortNodeId(nodeId)}` : definitionName;
}

// Runs - `app/schemas/workflow_run.py`

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "waiting_retry"
  | "needs_attention"
  | "budget_exceeded"
  | "failed"
  | "cancelled"
  | "succeeded";

export type NodeRunStatus =
  | "pending"
  | "running"
  | "waiting"
  | "needs_attention"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

/** One run of a workflow. Mirrors `WorkflowRunRead`. */
export interface WorkflowRunRead {
  id: Uuid;
  workflow_id: Uuid;
  workflow_version_id: Uuid | null;
  mode: "real" | "test";
  status: WorkflowRunStatus;
  triggered_by: string;
  budget_limit: number | null;
  spent_cost: number;
  cost_is_partial: boolean;
  deadline_at: string | null;
  paused_reason: string | null;
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
  output: Record<string, unknown> | null;
  root_run_id: Uuid;
  causation_run_id: Uuid | null;
  /** The run this one retries; its succeeded steps were not run again. */
  retry_of_run_id: Uuid | null;
  depth: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string | null;
}

export interface WorkflowRunList {
  items: WorkflowRunRead[];
  total: number;
}

/** One step of a run, in one loop iteration. Mirrors `WorkflowNodeRunRead`. */
export interface WorkflowNodeRunRead {
  id: Uuid;
  node_instance_id: Uuid;
  scope_path: { loop_node_id: Uuid; index: number }[];
  status: NodeRunStatus;
  waiting_reason: string | null;
  attempts: number;
  cost: number;
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
  /** What the step handed on, once it succeeded; null before, and when it failed. */
  output: Record<string, unknown> | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface WorkflowNodeRunList {
  items: WorkflowNodeRunRead[];
  total: number;
}

/** A file one of the run's steps stored. Mirrors `WorkflowFileRead`. */
export interface WorkflowRunFile {
  id: Uuid;
  filename: string | null;
  content_type: string;
  byte_size: number;
  producing_node_run_id: Uuid | null;
  created_at: string;
}

export interface WorkflowRunFileList {
  items: WorkflowRunFile[];
}

/** What starting a run sends. Mirrors `WorkflowRunStart`. */
export interface WorkflowRunStart {
  workflow_id: Uuid;
  mode?: "real" | "test";
  input?: Record<string, unknown>;
  /** Test only this step of the draft, with what earlier steps are known to hand on. */
  step?: { node_id: Uuid; outputs: Record<Uuid, Record<string, unknown>> };
}

/** What a run history is narrowed to, and which page of it. */
export interface RunHistoryQuery {
  /** One workflow's runs; every workflow the caller may see when unset. */
  workflowId?: Uuid;
  status?: WorkflowRunStatus;
  mode?: "real" | "test";
  triggeredBy?: string;
  /** Zero-based. */
  page: number;
}

/** Whether a run can be retried from where it stopped. Mirrors `_RETRYABLE`. */
export function isRunRetryable(status: WorkflowRunStatus): boolean {
  return ["failed", "cancelled", "budget_exceeded"].includes(status);
}

/** Whether a run has ended for good. */
export function isRunTerminal(status: WorkflowRunStatus): boolean {
  return ["succeeded", "failed", "cancelled", "budget_exceeded"].includes(status);
}

/** The two ways a workflow runs with nobody pressing Start. */
export type ExposureAdapter = "webhook" | "schedule";

/** A schedule's cadence: every N seconds, or a crontab evaluated in UTC. */
export type ExposureScheduleKind = "interval" | "cron";

/**
 * A workflow's webhook or schedule - its trigger node, switched on by a publish.
 * Mirrors `WorkflowExposureRead`. The version it runs is the one that switched
 * it on, and it runs as the member who published that version.
 */
export interface WorkflowExposureRead {
  id: Uuid;
  workflow_id: Uuid;
  workflow_version_id: Uuid;
  version_number: number;
  node_instance_id: Uuid;
  adapter: ExposureAdapter;
  is_active: boolean;
  execution_principal_user_id: Uuid | null;
  run_input: Record<string, unknown>;
  schedule_kind: ExposureScheduleKind | null;
  interval_seconds: number | null;
  cron_expression: string | null;
  next_fire_at: string | null;
  last_fired_at: string | null;
  last_run_id: Uuid | null;
  /** Where a webhook's deliveries are POSTed - the deployment's public API address. */
  webhook_url: string | null;
  created_at: string | null;
}

/** The rotate response - carries a webhook's new signing secret, once. */
export interface WorkflowExposureWithSecret extends WorkflowExposureRead {
  reveal_secret: string;
}

/** A webhook's test URL for the draft, open for one call. Mirrors `WebhookTestListening`. */
export interface WebhookTestListening {
  test_token: string;
  url: string;
  expires_at: string;
}

/** Where a test URL stands, and the call it caught. Mirrors `WebhookTestCapture`. */
export interface WebhookTestCapture {
  state: "listening" | "caught" | "expired";
  delivery: { body: Record<string, unknown>; delivery_id: string } | null;
}

/** Pause or resume it. Mirrors `WorkflowExposureUpdate`. */
export interface WorkflowExposureUpdate {
  is_active: boolean;
}

// Approvals - `app/schemas/workflow_approval.py`

export type WorkflowApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "cancelled";

/** One `human.approval` step's request, as the approver sees it. */
export interface WorkflowApprovalRead {
  id: Uuid;
  workflow_id: Uuid;
  workflow_name: string;
  workflow_run_id: Uuid;
  node_run_id: Uuid;
  title: string;
  details: string | null;
  /** Who may decide it; empty means anyone holding `approvals:decide`. */
  approver_user_ids: Uuid[];
  status: WorkflowApprovalStatus;
  expires_at: string | null;
  decided_by_user_id: Uuid | null;
  decided_at: string | null;
  note: string | null;
  created_at: string;
}

export interface WorkflowApprovalList {
  items: WorkflowApprovalRead[];
  total: number;
}

/** Rename a workflow, describe it or tag it. An absent field is kept. Mirrors `WorkflowUpdate`. */
export interface WorkflowUpdate {
  name?: string;
  description?: string | null;
  tags?: string[];
}
