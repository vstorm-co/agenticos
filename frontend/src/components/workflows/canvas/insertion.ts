import { deriveScopes } from "@/components/workflows/validation/topology";
import type { NodeInsertion } from "@/stores/workflow-editor-store";
import type {
  Binding,
  NodeDefinition,
  NodeInstance,
  NodePosition,
  Port,
  Uuid,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { isTrigger, triggerNodeOf } from "@/lib/workflows/triggers";

import { autoBindings, isConnectionValid, isErrorPort } from "./graph-adapter";
import { currentScopeId, scopedGraph } from "./scope-view";

/**
 * Where a new step goes and what it connects to - the part of adding a node that
 * decides, kept pure so every case is a unit test.
 *
 * A step is added *after* something: the node and port it was asked for (the "+"
 * beside an output), else the one selected node, else the end of the scope in
 * view - the rightmost node with an output still free. It lands to that node's
 * right, clear of every other node, and is wired to it when the ports fit, with
 * the bindings a same-shaped wire implies. So building a straight flow is a run
 * of clicks in the palette, and nothing ever lands on top of something else.
 *
 * Three cases are different. A workflow starts from one trigger, so a trigger
 * added to a workflow that has one *replaces* it: it takes the old one's place,
 * its wires and the bindings read from it. A step with no input otherwise - a
 * first trigger - goes *before* the workflow's current start, becomes the entry
 * and is wired into it. And inside a loop body every new step is wired in: body
 * membership is derived from the wires out of the loop, so an unwired step would
 * drop out of the body the user is looking at and reappear at the top level.
 */

/** The footprint a node card takes on the canvas, for placement only. */
export const NODE_WIDTH = 240;
export const NODE_HEIGHT = 88;
/** The space left between one step and the next along a flow, and between rows. */
const GAP_X = 80;
const GAP_Y = 32;
/** How far a step is pushed down looking for room before it settles anyway. */
const MAX_ROWS = 40;

/** Where a new node was asked to attach, when it was: a node and one of its outputs. */
export interface InsertFrom {
  nodeId: Uuid;
  portId: string;
}

export interface InsertionRequest {
  /** The whole working graph. */
  graph: WorkflowGraph;
  /** Every node's resolved definition, keyed by node id. */
  definitions: Map<string, NodeDefinition | null>;
  /** The loop scopes the canvas is inside, root to current. */
  scopePath: readonly Uuid[];
  /** The ids of the nodes selected on the canvas. */
  selectedIds: readonly Uuid[];
  /** The step being added. */
  definition: NodeDefinition;
  /** The node and output it is added after, when one was named. */
  from?: InsertFrom;
  /** Where it was dropped, when it was dragged onto the canvas. */
  dropAt?: NodePosition;
  /** The new node's id - a parameter so a plan is deterministic under test. */
  id?: Uuid;
}

/** The graph with its loop scopes derived from its wires as they are now. */
export function withLiveScopes(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): WorkflowGraph {
  return { ...graph, scopes: deriveScopes(graph, definitions) };
}

function overlaps(a: NodePosition, b: NodePosition): boolean {
  return Math.abs(a.x - b.x) < NODE_WIDTH + GAP_X / 2 && Math.abs(a.y - b.y) < NODE_HEIGHT;
}

/** `preferred`, or the first spot below it that no node in `nodes` covers. */
export function clearOf(nodes: readonly NodeInstance[], preferred: NodePosition): NodePosition {
  let position = preferred;
  for (let row = 0; row < MAX_ROWS; row += 1) {
    if (!nodes.some((node) => overlaps(node.layout, position))) return position;
    position = { x: position.x, y: position.y + NODE_HEIGHT + GAP_Y };
  }
  return position;
}

function outputsOf(definition: NodeDefinition | null): Port[] {
  return definition?.ports.filter((port) => port.kind === "output") ?? [];
}

function inputsOf(definition: NodeDefinition | null): Port[] {
  return definition?.ports.filter((port) => port.kind === "input") ?? [];
}

/** An output with no wire leaving it yet: each port carries one wire. */
function freeOutput(
  graph: WorkflowGraph,
  node: NodeInstance,
  definition: NodeDefinition | null,
): Port | null {
  const used = new Set(
    graph.edges.filter((edge) => edge.source_node_id === node.id).map((edge) => edge.source_port),
  );
  return outputsOf(definition).find((port) => !isErrorPort(port) && !used.has(port.id)) ?? null;
}

/** The end of a flow: the rightmost node in view that still has an output free. */
function tail(
  graph: WorkflowGraph,
  visible: readonly NodeInstance[],
  definitions: Map<string, NodeDefinition | null>,
): { node: NodeInstance; port: Port } | null {
  let best: { node: NodeInstance; port: Port } | null = null;
  for (const node of visible) {
    const port = freeOutput(graph, node, definitions.get(node.id) ?? null);
    if (port === null) continue;
    if (best === null || node.layout.x > best.node.layout.x) best = { node, port };
  }
  return best;
}

/** What the new node attaches after: an explicit port, the selection, or the tail. */
function anchorFor(
  request: InsertionRequest,
  graph: WorkflowGraph,
  visible: readonly NodeInstance[],
): { node: NodeInstance; portId: string } | null {
  const { definitions, from, selectedIds, scopePath } = request;
  const byId = new Map(graph.nodes.map((node) => [node.id, node] as const));
  if (from !== undefined) {
    const node = byId.get(from.nodeId);
    return node === undefined ? null : { node, portId: from.portId };
  }
  const visibleIds = new Set(visible.map((node) => node.id));
  const selected = selectedIds.filter((id) => visibleIds.has(id));
  const only = selected.length === 1 ? visible.find((node) => node.id === selected[0]) : undefined;
  if (only !== undefined) {
    const port = freeOutput(graph, only, definitions.get(only.id) ?? null);
    if (port !== null) return { node: only, portId: port.id };
  }
  const end = tail(graph, visible, definitions);
  if (end !== null) return { node: end.node, portId: end.port.id };
  // An empty loop body starts from the loop itself, through the port its body hangs off.
  const scopeId = currentScopeId(scopePath);
  const owner = scopeId === null ? undefined : byId.get(scopeId);
  const bodyPort =
    owner === undefined ? undefined : outputsOf(definitions.get(owner.id) ?? null)[0];
  return owner === undefined || bodyPort === undefined
    ? null
    : { node: owner, portId: bodyPort.id };
}

/** The wire from `source` into `target`, when the ports fit - else none. */
function wire(
  source: { nodeId: Uuid; portId: string },
  target: { nodeId: Uuid; portId: string },
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): { edge: WorkflowEdge; bindings: Binding[] } | null {
  const connection = {
    source: source.nodeId,
    sourceHandle: source.portId,
    target: target.nodeId,
    targetHandle: target.portId,
  };
  if (!isConnectionValid(connection, definitions)) return null;
  return {
    edge: {
      id: crypto.randomUUID(),
      source_node_id: source.nodeId,
      source_port: source.portId,
      target_node_id: target.nodeId,
      target_port: target.portId,
    },
    bindings: autoBindings(connection, graph, definitions),
  };
}

/** Plan adding `definition` to the graph: where it goes and what it is wired to. */
export function planInsertion(request: InsertionRequest): NodeInsertion {
  const { definition, dropAt, scopePath } = request;
  const id = request.id ?? crypto.randomUUID();
  const graph = withLiveScopes(request.graph, request.definitions);
  const visible = scopedGraph(graph, scopePath).nodes;
  const definitions = new Map(request.definitions);
  definitions.set(id, definition);
  const input = inputsOf(definition)[0];

  if (input === undefined && isTrigger(definition) && scopePath.length === 0) {
    const current = triggerNodeOf(graph, request.definitions);
    if (current !== null) {
      return {
        node: { ...blank(definition, id), layout: dropAt ?? current.layout },
        edge: null,
        bindings: [],
        becomesEntry: current.id === graph.entry_node_id,
        replaces: current.id,
      };
    }
  }

  // A starting step goes before the current start, and becomes it.
  if (input === undefined) {
    const entry = graph.nodes.find((node) => node.id === graph.entry_node_id);
    const entryInput =
      entry === undefined ? undefined : inputsOf(definitions.get(entry.id) ?? null)[0];
    const atRoot = scopePath.length === 0;
    const position =
      dropAt ??
      clearOf(
        visible,
        entry === undefined
          ? { x: 0, y: 0 }
          : { x: entry.layout.x - NODE_WIDTH - GAP_X, y: entry.layout.y },
      );
    const node = { ...blank(definition, id), layout: position };
    const output = outputsOf(definition).find((port) => !isErrorPort(port));
    const link =
      atRoot && entry !== undefined && entryInput !== undefined && output !== undefined
        ? wire(
            { nodeId: id, portId: output.id },
            { nodeId: entry.id, portId: entryInput.id },
            graph,
            definitions,
          )
        : null;
    return {
      node,
      edge: link?.edge ?? null,
      bindings: link?.bindings ?? [],
      becomesEntry: atRoot && (entry === undefined || entryInput !== undefined),
      replaces: null,
    };
  }

  // A drop at the top level is placed where it fell and left for the user to wire;
  // everywhere else the step attaches after its anchor.
  const anchor =
    dropAt !== undefined && scopePath.length === 0 && request.from === undefined
      ? null
      : anchorFor(request, graph, visible);
  const after = (node: NodeInstance): NodePosition => ({
    x: node.layout.x + NODE_WIDTH + GAP_X,
    y: node.layout.y,
  });
  const rightmost = visible.reduce<NodeInstance | null>(
    (best, node) => (best === null || node.layout.x > best.layout.x ? node : best),
    null,
  );
  const position =
    dropAt ??
    clearOf(
      visible,
      anchor !== null ? after(anchor.node) : rightmost !== null ? after(rightmost) : { x: 0, y: 0 },
    );
  const link =
    anchor === null
      ? null
      : wire(
          { nodeId: anchor.node.id, portId: anchor.portId },
          { nodeId: id, portId: input.id },
          graph,
          definitions,
        );
  return {
    node: { ...blank(definition, id), layout: position },
    edge: link?.edge ?? null,
    bindings: link?.bindings ?? [],
    becomesEntry: graph.nodes.length === 0,
    replaces: null,
  };
}

function blank(definition: NodeDefinition, id: Uuid): NodeInstance {
  return {
    id,
    definition_id: definition.id,
    definition_version: definition.version,
    config: {},
    layout: { x: 0, y: 0 },
  };
}
