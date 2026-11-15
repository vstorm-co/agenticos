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

import { ownsAScope } from "@/components/workflows/palette/scope";
import { isTrigger, triggerNodeOf } from "@/lib/workflows/triggers";

import { NODE_HEIGHT, NODE_WIDTH, cardHeight, stepFootprint, type Footprint } from "./node-size";
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
 * Additional triggers are independent roots and preserve existing starts and wires.
 * The first trigger goes before a legacy non-trigger entry. A step added inside a
 * loop's body names that loop (`scope_id`), so it stays in the body whether or not
 * anything is wired to it, and a new loop comes with its **Loop item** and **Loop
 * result** already inside it.
 */

/** The space left between one step and the next along a flow, and between rows. */
const GAP_X = 80;
const GAP_Y = 24;
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
  /** The connection it goes into the middle of, when one was chosen. */
  between?: WorkflowEdge;
  /** The new node's id - a parameter so a plan is deterministic under test. */
  id?: Uuid;
  /** The catalog's loop item and result steps, put inside a new loop; none without them. */
  loopSteps?: LoopSteps;
}

/** The two steps every loop body holds: where an iteration starts and what it hands back. */
export interface LoopSteps {
  item: NodeDefinition;
  result: NodeDefinition;
}

/** The catalog's newest loop item and result steps, or none when it lacks either. */
export function loopStepsOf(catalog: readonly NodeDefinition[]): LoopSteps | undefined {
  const newest = (id: string): NodeDefinition | undefined =>
    catalog
      .filter((definition) => definition.id === id)
      .reduce<NodeDefinition | undefined>(
        (best, definition) =>
          best === undefined || definition.version > best.version ? definition : best,
        undefined,
      );
  const item = newest("loop.item");
  const result = newest("loop.yield");
  return item === undefined || result === undefined ? undefined : { item, result };
}

/** The graph with its loop scopes derived from its wires as they are now. */
export function withLiveScopes(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
): WorkflowGraph {
  return { ...graph, scopes: deriveScopes(graph, definitions) };
}

/** A step's footprint when nothing says otherwise: the size it was given, else the default. */
function defaultFootprint(node: NodeInstance): Footprint {
  return { width: node.layout.width ?? NODE_WIDTH, height: node.layout.height ?? NODE_HEIGHT };
}

/** Whether a card of size `own` at `at` would touch `node`, or come closer than the gaps: room for a wire between columns. */
function overlaps(node: NodeInstance, size: Footprint, at: NodePosition, own: Footprint): boolean {
  return (
    at.x < node.layout.x + size.width + GAP_X / 2 &&
    node.layout.x < at.x + own.width + GAP_X / 2 &&
    at.y < node.layout.y + size.height + GAP_Y &&
    node.layout.y < at.y + own.height + GAP_Y
  );
}

/**
 * `preferred`, or the first spot below it that no node in `nodes` covers - a card
 * of size `own`, against each node's own `footprint`. A spot is moved to just
 * under the lowest card in its way.
 */
export function clearOf(
  nodes: readonly NodeInstance[],
  preferred: NodePosition,
  footprint: (node: NodeInstance) => Footprint = defaultFootprint,
  own: Footprint = { width: NODE_WIDTH, height: NODE_HEIGHT },
): NodePosition {
  let position = preferred;
  for (let row = 0; row < MAX_ROWS; row += 1) {
    const at = position;
    const blocking = nodes.filter((node) => overlaps(node, footprint(node), at, own));
    if (blocking.length === 0) return position;
    const bottom = Math.max(...blocking.map((node) => node.layout.y + footprint(node).height));
    position = { x: position.x, y: bottom + GAP_Y };
  }
  return position;
}

/** Each node's footprint as the canvas draws it, and the one a new `definition` would take. */
function footprintsFor(
  graph: WorkflowGraph,
  definitions: Map<string, NodeDefinition | null>,
  definition: NodeDefinition,
): { footprint: (node: NodeInstance) => Footprint; own: Footprint } {
  return {
    footprint: (node) => stepFootprint(node, definitions.get(node.id) ?? null, graph.bindings),
    own: {
      width: NODE_WIDTH,
      height: cardHeight(
        {
          id: "",
          definition_id: definition.id,
          definition_version: definition.version,
          config: {},
          layout: { x: 0, y: 0 },
        },
        definition,
        [],
      ),
    },
  };
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
  const { definitions, from, selectedIds } = request;
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
  // Nothing in view has a way out left: the step is added unwired. Never from the loop
  // itself - no wire enters a body, which starts at its Loop item.
  return end === null ? null : { node: end.node, portId: end.port.id };
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
  const scopeId = currentScopeId(scopePath);
  const blank = (def: NodeDefinition, nodeId: Uuid): NodeInstance =>
    blankStep(def, nodeId, scopeId);
  const graph = withLiveScopes(request.graph, request.definitions);
  const visible = scopedGraph(graph, scopePath).nodes;
  const definitions = new Map(request.definitions);
  definitions.set(id, definition);
  const input = inputsOf(definition)[0];
  const { footprint, own } = footprintsFor(graph, definitions, definition);

  if (
    input === undefined &&
    isTrigger(definition) &&
    scopePath.length === 0 &&
    triggerNodeOf(graph, request.definitions) !== null
  ) {
    const first = graph.nodes.find((node) => node.id === graph.entry_node_id);
    return {
      node: {
        ...blank(definition, id),
        layout:
          dropAt ??
          clearOf(
            visible,
            { x: first?.layout.x ?? 0, y: (first?.layout.y ?? 0) + NODE_HEIGHT + GAP_Y },
            footprint,
            own,
          ),
      },
      edge: null,
      bindings: [],
      becomesEntry: false,
      replaces: null,
    };
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
        footprint,
        own,
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

  // A new loop's body comes with it however the loop is placed, dropped onto a wire too.
  const companions =
    request.loopSteps !== undefined && ownsAScope(definition)
      ? loopBody(request.loopSteps, id)
      : undefined;
  const withBody = (planned: NodeInsertion): NodeInsertion =>
    companions === undefined ? planned : { ...planned, companions };

  if (request.between !== undefined) {
    const planned = splitting(request.between, graph, visible, definitions, definition, id);
    if (planned !== null) return withBody(planned);
  }

  // A drop at the top level is placed where it fell and left for the user to wire;
  // everywhere else the step attaches after its anchor.
  const anchor =
    dropAt !== undefined && scopePath.length === 0 && request.from === undefined
      ? null
      : anchorFor(request, graph, visible);
  const after = (node: NodeInstance): NodePosition => ({
    x: node.layout.x + footprint(node).width + GAP_X,
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
      footprint,
      own,
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
  return withBody({
    node: { ...blank(definition, id), layout: position },
    edge: link?.edge ?? null,
    bindings: link?.bindings ?? [],
    becomesEntry: graph.nodes.length === 0,
    replaces: null,
  });
}

/**
 * A new loop's body: its Loop item at the left and its Loop result to the right,
 * with room between for the steps the builder adds after the item. Left unwired -
 * the steps between them are the builder's to choose.
 */
function loopBody(steps: LoopSteps, loopId: Uuid): NodeInstance[] {
  return [
    { ...blankStep(steps.item, crypto.randomUUID(), loopId), layout: { x: 0, y: 0 } },
    {
      ...blankStep(steps.result, crypto.randomUUID(), loopId),
      layout: { x: 3 * (NODE_WIDTH + GAP_X), y: 0 },
    },
  ];
}

/**
 * The step put into the middle of `edge`: halfway between its ends, the wire from
 * the source now into it, and a wire from it on to where the old one led when
 * their ports fit. `null` when the source cannot feed the new step at all - then
 * the connection is left as it was and the step is added the ordinary way.
 *
 * The bindings the far end had keep reading what they read: the source still
 * runs before it, now one step further back.
 */
function splitting(
  edge: WorkflowEdge,
  graph: WorkflowGraph,
  visible: readonly NodeInstance[],
  definitions: Map<string, NodeDefinition | null>,
  definition: NodeDefinition,
  id: Uuid,
): NodeInsertion | null {
  const byId = new Map(graph.nodes.map((node) => [node.id, node] as const));
  const source = byId.get(edge.source_node_id);
  const target = byId.get(edge.target_node_id);
  const input = inputsOf(definition)[0];
  if (source === undefined || target === undefined || input === undefined) return null;
  const { footprint, own } = footprintsFor(graph, definitions, definition);
  // Judged as if the old wire were gone, since it is about to be: a port takes one.
  const without = { ...graph, edges: graph.edges.filter((item) => item.id !== edge.id) };
  const head = wire(
    { nodeId: source.id, portId: edge.source_port },
    { nodeId: id, portId: input.id },
    without,
    definitions,
  );
  if (head === null) return null;
  const output = outputsOf(definition).find((port) => !isErrorPort(port));
  const onward =
    output === undefined
      ? null
      : wire(
          { nodeId: id, portId: output.id },
          { nodeId: target.id, portId: edge.target_port },
          without,
          definitions,
        );
  const middle = {
    x: (source.layout.x + target.layout.x) / 2,
    y: (source.layout.y + target.layout.y) / 2,
  };
  return {
    node: {
      ...blankStep(definition, id, source.scope_id ?? null),
      layout: clearOf(visible, middle, footprint, own),
    },
    edge: head.edge,
    bindings: head.bindings,
    becomesEntry: false,
    replaces: null,
    split: { edgeId: edge.id, tail: onward?.edge ?? null },
  };
}

function blankStep(definition: NodeDefinition, id: Uuid, scopeId: Uuid | null): NodeInstance {
  return {
    id,
    definition_id: definition.id,
    definition_version: definition.version,
    config: {},
    layout: { x: 0, y: 0 },
    ...(scopeId !== null ? { scope_id: scopeId } : {}),
  };
}
