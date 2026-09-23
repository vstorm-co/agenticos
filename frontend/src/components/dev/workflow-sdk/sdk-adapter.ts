import type { IconType, WorkflowBuilderEdge, WorkflowBuilderNode } from "@workflowbuilder/sdk";

import type {
  GraphEdge,
  GraphNode,
  NodeConfig,
  NodeKind,
  TableColumnMapping,
  TableWriteMode,
  WorkflowGraph,
} from "./typed-graph";

/**
 * Typed graph scope <-> the SDK's `{ nodes, edges }`.
 *
 * The SDK edits exactly one flat scope. A foreach's body is not an SDK concept
 * (there is no parent/child node in the SDK), so the body never enters the SDK:
 * it stays in the typed graph, keyed by the foreach node's id, and is re-attached
 * when the scope comes back. Editing a body is a scope switch, not a nested canvas.
 */

const ICONS: Record<NodeKind, IconType> = {
  start: "Lightning",
  end: "Flag",
  agent: "AiAgent",
  table_write: "Table",
  foreach: "Repeat",
};

/**
 * xyflow's `node.type`, which the SDK resolves to a renderer: its `NodeType` enum
 * values, written out so this module (and its tests) never load the SDK, whose
 * stylesheet imports Node cannot read.
 */
const TEMPLATE_TYPE: Record<NodeKind, string> = {
  start: "start-node",
  end: "node",
  agent: "node",
  table_write: "node",
  foreach: "node",
};

type Properties = Record<string, unknown>;

function propertiesOf(config: NodeConfig, label: string): Properties {
  switch (config.kind) {
    case "start":
    case "end":
      return { label };
    case "agent":
      return {
        label,
        agent_id: config.agent_id,
        version_id: config.version_id,
        prompt: config.prompt,
      };
    case "table_write":
      return {
        label,
        table_id: config.table_id,
        mode: config.mode,
        key_column: config.key_column ?? "",
        batch_size: config.batch_size,
        mappings: config.mappings,
      };
    case "foreach":
      return { label, items: config.items, concurrency: config.concurrency };
  }
}

export interface SdkScope {
  nodes: WorkflowBuilderNode[];
  edges: WorkflowBuilderEdge[];
}

export function toSdkScope(scope: WorkflowGraph): SdkScope {
  return {
    nodes: scope.nodes.map((node) => ({
      id: node.id,
      type: TEMPLATE_TYPE[node.config.kind],
      position: node.position,
      data: {
        type: node.config.kind,
        icon: ICONS[node.config.kind],
        properties: propertiesOf(node.config, node.label),
      },
    })),
    edges: scope.edges.map((edge) => ({
      id: edge.id,
      type: "labelEdge",
      source: edge.source,
      target: edge.target,
      sourceHandle: "source",
      targetHandle: "target",
    })),
  };
}

export class GraphParseError extends Error {
  constructor(readonly problems: readonly string[]) {
    super(`the SDK document does not describe a valid graph: ${problems.join("; ")}`);
    this.name = "GraphParseError";
  }
}

const MODES: readonly TableWriteMode[] = ["insert", "upsert", "update"];

function str(props: Properties, key: string, where: string, problems: string[]): string {
  const value = props[key];
  if (typeof value === "string") return value;
  problems.push(`${where}.${key} is ${JSON.stringify(value)}, expected a string`);
  return "";
}

function mappings(props: Properties, where: string, problems: string[]): TableColumnMapping[] {
  const raw = props.mappings ?? [];
  if (!Array.isArray(raw)) {
    problems.push(`${where}.mappings is not a list`);
    return [];
  }
  return raw.flatMap((row: unknown, index) => {
    if (
      typeof row === "object" &&
      row !== null &&
      typeof (row as Properties).column === "string" &&
      typeof (row as Properties).value === "string"
    ) {
      const { column, value } = row as { column: string; value: string };
      // The SDK's schema cannot say an array item's property is required, so a
      // half-filled row reaches this far. Refuse it here.
      if (column === "") problems.push(`${where}.mappings[${index}] has no column`);
      return [{ column, value }];
    }
    problems.push(`${where}.mappings[${index}] needs a string column and value`);
    return [];
  });
}

function configOf(
  kind: string,
  props: Properties,
  original: GraphNode | undefined,
  where: string,
  problems: string[],
): NodeConfig {
  switch (kind) {
    case "start":
      return { kind: "start" };
    case "end":
      return { kind: "end" };
    case "agent":
      return {
        kind: "agent",
        agent_id: str(props, "agent_id", where, problems),
        version_id: str(props, "version_id", where, problems),
        prompt: str(props, "prompt", where, problems),
      };
    case "table_write": {
      const mode = props.mode;
      if (!MODES.includes(mode as TableWriteMode)) {
        problems.push(`${where}.mode is ${JSON.stringify(mode)}`);
      }
      const batch = props.batch_size;
      if (typeof batch !== "number" || !Number.isInteger(batch) || batch < 1) {
        problems.push(`${where}.batch_size is ${JSON.stringify(batch)}, expected an integer >= 1`);
      }
      const key = str(props, "key_column", where, problems);
      return {
        kind: "table_write",
        table_id: str(props, "table_id", where, problems),
        mode: MODES.includes(mode as TableWriteMode) ? (mode as TableWriteMode) : "insert",
        key_column: key === "" ? null : key,
        batch_size: typeof batch === "number" ? batch : 100,
        mappings: mappings(props, where, problems),
        // A field the SDK cannot edit is not the SDK's to drop.
        on_conflict: original?.config.kind === "table_write" ? original.config.on_conflict : {},
      };
    }
    case "foreach": {
      const concurrency = props.concurrency;
      if (typeof concurrency !== "number" || !Number.isInteger(concurrency) || concurrency < 1) {
        problems.push(
          `${where}.concurrency is ${JSON.stringify(concurrency)}, expected an integer >= 1`,
        );
      }
      const body =
        original?.config.kind === "foreach" ? original.config.body : { nodes: [], edges: [] };
      return {
        kind: "foreach",
        items: str(props, "items", where, problems),
        concurrency: typeof concurrency === "number" ? concurrency : 1,
        body,
      };
    }
    default:
      problems.push(`${where} has unknown node type ${JSON.stringify(kind)}`);
      return { kind: "end" };
  }
}

/**
 * Read an SDK scope back into a typed one. `original` supplies what the SDK never
 * held (foreach bodies). Anything that does not parse is reported, never patched
 * up: a save that silently coerces is how a graph gets corrupted.
 */
export function fromSdkScope(
  original: WorkflowGraph,
  nodes: readonly WorkflowBuilderNode[],
  edges: readonly WorkflowBuilderEdge[],
): WorkflowGraph {
  const problems: string[] = [];
  const byId = new Map(original.nodes.map((node) => [node.id, node]));
  const ids = new Set<string>();

  const graphNodes: GraphNode[] = nodes.map((node) => {
    const where = `node ${node.id}`;
    if (ids.has(node.id)) problems.push(`${where} appears twice`);
    ids.add(node.id);
    // `errors` and `customErrors` are validation results the SDK writes into
    // `properties` itself. They are derived, so they are dropped, not persisted.
    const { errors: _errors, customErrors: _customErrors, ...props } = node.data.properties;
    void _errors;
    void _customErrors;
    const label = typeof props.label === "string" ? props.label : "";
    return {
      id: node.id,
      label,
      position: { x: node.position.x, y: node.position.y },
      config: configOf(node.data.type, props, byId.get(node.id), where, problems),
    };
  });

  const graphEdges: GraphEdge[] = edges.map((edge) => {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      problems.push(
        `edge ${edge.id} joins ${edge.source} to ${edge.target}, which is not in this scope`,
      );
    }
    return { id: edge.id, source: edge.source, target: edge.target };
  });

  if (problems.length > 0) throw new GraphParseError(problems);
  return { nodes: graphNodes, edges: graphEdges };
}
