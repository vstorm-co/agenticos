/**
 * The eight structural rules (plus the required-inputs rule the property panel
 * mirrors, and required settings left empty), each a pure function over the in-memory graph and the resolved catalog
 * — the client mirror of `validate.py`'s Pass 1. Every rule returns
 * {@link RawProblem}s and never translates; `validateGraph` renders them.
 *
 * What is deliberately **not** mirrored, because the client cannot compute it and
 * publish re-checks it server-side: the graph size ceiling (a deployment setting),
 * per-node granted scopes (deployment-wide), `config` against its `config_schema`
 * (a Pydantic validation), `TableIORef` resolution (a database lookup), a
 * `LiteralValue`'s type (a Python type check) and a binding's target-field
 * existence. Those are the resource-resolution pass, authoritative on the server;
 * the binding form marks an unfilled required field for the editor's own sake.
 */

import {
  outputRefs,
  type Binding,
  type JsonSchema,
  type NodeOutputRef,
  type ScopeBoundary,
  type WorkflowEdge,
  type WorkflowGraph,
} from "@/lib/workflows/types";

import {
  portShapesCompatible,
  portSchema,
  resolveFieldType,
  fieldType,
  typesCompatible,
  UNKNOWN,
} from "./schema";
import { ERROR_PORT } from "@/lib/workflows/ports";
import { isTrigger } from "@/lib/workflows/triggers";
import { definitionFor, forwardEdges, kahn, nodeIds, type DefinitionMap } from "./topology";
import type { RawProblem } from "./types";

/**
 * The steps that leave by exactly one output port on every run, so a merge may
 * rejoin their branches - `validate.py`'s `EXCLUSIVE_BRANCHING`, less
 * `error.handle`, whose branches the client does not mirror.
 */
const EXCLUSIVE_BRANCHING: ReadonlySet<string> = new Set([
  "logic.if",
  "logic.switch",
  "decide.yes_no",
  "decide.choose",
  "decide.score",
  "table.exists",
  "table.record.exists",
  "human.approval",
]);

function node(nodeId: string, code: RawProblem["code"], params?: RawProblem["params"]): RawProblem {
  return { nodeId, edgeId: null, field: null, code, params };
}

function nodeField(nodeId: string, field: string, code: RawProblem["code"]): RawProblem {
  return { nodeId, edgeId: null, field, code };
}

function edge(edgeId: string, code: RawProblem["code"]): RawProblem {
  return { nodeId: null, edgeId, field: null, code };
}

function graphLevel(code: RawProblem["code"]): RawProblem {
  return { nodeId: null, edgeId: null, field: null, code };
}

// Dangling references — every edge and binding must name nodes in the graph.

export function danglingReferences(graph: WorkflowGraph): RawProblem[] {
  const ids = nodeIds(graph);
  const problems: RawProblem[] = [];
  for (const e of graph.edges) {
    if (!ids.has(e.source_node_id)) problems.push(edge(e.id, "edge-source-node-missing"));
    if (!ids.has(e.target_node_id)) problems.push(edge(e.id, "edge-target-node-missing"));
  }
  for (const binding of graph.bindings) {
    if (!ids.has(binding.target_node_id)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-target-node-missing"),
      );
    }
    if (outputRefs(binding.source).some((ref) => !ids.has(ref.node_id))) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-source-node-missing"),
      );
    }
  }
  return problems;
}

// Resource resolution the client can mirror — an unknown definition version.

export function missingVersions(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  return graph.nodes
    .filter((n) => definitionFor(definitions, n.id) === null)
    .map((n) =>
      node(n.id, "unknown-definition", {
        definitionId: n.definition_id,
        version: n.definition_version,
      }),
    );
}

// Rule 1 — exactly one input, and a trigger is it.

/**
 * The entry is a node no edge reaches, and a workflow starts from one trigger:
 * any trigger that is not the entry is refused on its own node, since it names a
 * way in that would never run the steps after it.
 */
export function rule1SingleEntry(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  if (!nodeIds(graph).has(graph.entry_node_id)) return [graphLevel("entry-not-in-graph")];
  const incoming = new Set(graph.edges.map((e) => e.target_node_id));
  if (incoming.has(graph.entry_node_id)) return [graphLevel("entry-is-edge-target")];
  return graph.nodes
    .filter((n) => n.id !== graph.entry_node_id && isTrigger(definitionFor(definitions, n.id)))
    .map((n) => node(n.id, "trigger-not-entry"));
}

// Rule 2 — reachable outputs.

export function rule2ReachableOutputs(
  graph: WorkflowGraph,
  nodeScope: Map<string, string>,
): RawProblem[] {
  if (!nodeIds(graph).has(graph.entry_node_id)) return [];
  const topLevel = graph.nodes.filter((n) => !nodeScope.has(n.id)).map((n) => n.id);
  const adjacency = forwardEdges(graph);
  const seen = new Set<string>();
  const queue: string[] = [graph.entry_node_id];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    if (seen.has(current)) continue;
    seen.add(current);
    for (const e of adjacency.get(current) ?? []) {
      const targetScope = nodeScope.get(e.target_node_id);
      const target = targetScope === undefined ? e.target_node_id : targetScope;
      if (!seen.has(target)) queue.push(target);
    }
  }
  return topLevel.filter((id) => !seen.has(id)).map((id) => node(id, "unreachable-node"));
}

// Rule 3 — type compatibility.

export function rule3TypeCompatibility(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const e of graph.edges) {
    const sourceDefinition = definitionFor(definitions, e.source_node_id);
    const targetDefinition = definitionFor(definitions, e.target_node_id);
    if (sourceDefinition === null || targetDefinition === null) continue;
    const sourceSchema = portSchema(sourceDefinition, e.source_port, "output");
    if (sourceSchema === UNKNOWN) {
      problems.push(edge(e.id, "edge-source-port-unknown"));
      continue;
    }
    const targetSchema = portSchema(targetDefinition, e.target_port, "input");
    if (targetSchema === UNKNOWN) {
      problems.push(edge(e.id, "edge-target-port-unknown"));
      continue;
    }
    if (!portShapesCompatible(sourceSchema, targetSchema)) {
      problems.push(edge(e.id, "edge-incompatible"));
    }
  }
  for (const { binding, ref, templated } of outputReads(graph)) {
    const sourceDefinition = definitionFor(definitions, ref.node_id);
    const targetDefinition = definitionFor(definitions, binding.target_node_id);
    if (sourceDefinition === null || targetDefinition === null) continue;
    const sourceType = resolveFieldType(sourceDefinition, ref.port, ref.field_path);
    if (sourceType === UNKNOWN) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-field-path-unknown"),
      );
      continue;
    }
    // A placeholder becomes text whatever it holds; the field taking text is
    // checked once per template, below.
    if (templated) continue;
    const targetType = fieldType(targetDefinition, binding.target_field);
    if (targetType !== UNKNOWN && !typesCompatible(sourceType, targetType)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-incompatible"),
      );
    }
  }
  return problems;
}

/** A template makes text, so the field it is bound to must take text. */
export function templateTargets(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const binding of graph.bindings) {
    if (binding.source.kind !== "template") continue;
    const targetDefinition = definitionFor(definitions, binding.target_node_id);
    if (targetDefinition === null) continue;
    const targetType = fieldType(targetDefinition, binding.target_field);
    if (targetType !== UNKNOWN && !typesCompatible({ type: "string" }, targetType)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-template-not-text"),
      );
    }
  }
  return problems;
}

/**
 * Every read of another step's output: a binding reading one, or a template's
 * placeholder - each checked like a binding of its own, and flagged, since what a
 * placeholder holds becomes text.
 */
function outputReads(
  graph: WorkflowGraph,
): { binding: Binding; ref: NodeOutputRef; templated: boolean }[] {
  return graph.bindings.flatMap((binding) =>
    outputRefs(binding.source).map((ref) => ({
      binding,
      ref,
      templated: binding.source.kind === "template",
    })),
  );
}

// Rule 4 — branch-local data availability (dominators).

export function rule4BranchLocalAvailability(
  graph: WorkflowGraph,
  dominators: Map<string, Set<string>>,
): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const { binding, ref } of outputReads(graph)) {
    const sourceId = ref.node_id;
    const targetId = binding.target_node_id;
    if (sourceId === targetId) {
      problems.push(nodeField(targetId, binding.target_field, "binding-self-reference"));
      continue;
    }
    const targetDom = dominators.get(targetId);
    if (targetDom === undefined) continue;
    if (!targetDom.has(sourceId)) {
      problems.push(nodeField(targetId, binding.target_field, "binding-unavailable"));
    }
  }
  return problems;
}

// Rule 5 — exclusive merge.

export function rule5ExclusiveMerge(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
  dominators: Map<string, Set<string>>,
): RawProblem[] {
  const problems: RawProblem[] = [];
  const predecessors = new Map<string, string[]>();
  for (const e of graph.edges) {
    const list = predecessors.get(e.target_node_id);
    if (list === undefined) predecessors.set(e.target_node_id, [e.source_node_id]);
    else list.push(e.source_node_id);
  }

  for (const n of graph.nodes) {
    const definition = definitionFor(definitions, n.id);
    if (definition === null || definition.id !== "logic.merge") continue;
    const branches = predecessors.get(n.id) ?? [];
    if (branches.length < 2) continue;
    const distinct = new Set(branches);
    if (distinct.size !== branches.length) {
      problems.push(node(n.id, "merge-duplicate-branch"));
      continue;
    }
    const common = nearestCommonDominator(branches, dominators);
    if (common === null) {
      problems.push(node(n.id, "merge-no-common-dominator"));
      continue;
    }
    const commonDefinition = definitionFor(definitions, common);
    if (commonDefinition === null || !EXCLUSIVE_BRANCHING.has(commonDefinition.id)) {
      problems.push(node(n.id, "merge-not-from-if"));
      continue;
    }
    if (!branchesDivergeAt(common, distinct, graph, dominators)) {
      problems.push(node(n.id, "merge-not-exclusive"));
    }
  }
  return problems;
}

function branchesDivergeAt(
  common: string,
  branches: Set<string>,
  graph: WorkflowGraph,
  dominators: Map<string, Set<string>>,
): boolean {
  const seenPorts = new Set<string>();
  for (const branch of branches) {
    const branchDom = dominators.get(branch) ?? new Set<string>();
    const feedingPorts = new Set(
      graph.edges
        .filter((e) => e.source_node_id === common && branchDom.has(e.target_node_id))
        .map((e) => e.source_port),
    );
    if (feedingPorts.size === 0) return false;
    for (const port of feedingPorts) {
      if (seenPorts.has(port)) return false;
    }
    for (const port of feedingPorts) seenPorts.add(port);
  }
  return true;
}

export function nearestCommonDominator(
  nodes: readonly string[],
  dominators: Map<string, Set<string>>,
): string | null {
  const domSets = nodes.map((id) => dominators.get(id));
  if (domSets.some((set) => set === undefined)) return null;
  const resolved = domSets as Set<string>[];
  const common = intersectAll(resolved);
  if (common.size === 0) return null;
  for (const candidate of common) {
    const candidateDom = dominators.get(candidate) ?? new Set<string>();
    if ([...common].every((member) => candidateDom.has(member))) return candidate;
  }
  return null;
}

function intersectAll(sets: Set<string>[]): Set<string> {
  const [first, ...rest] = sets;
  let result = new Set(first);
  for (const set of rest) result = new Set([...result].filter((value) => set.has(value)));
  return result;
}

// Rule 6 — nested scope boundaries.

export function rule6NestedScopeBoundaries(
  graph: WorkflowGraph,
  scopes: readonly ScopeBoundary[],
  nodeScope: Map<string, string>,
): RawProblem[] {
  const entryBoundary = new Map<string, ScopeBoundary>();
  const exitBoundary = new Map<string, ScopeBoundary>();
  for (const scope of scopes) {
    entryBoundary.set(scope.scope_node_id, scope);
    exitBoundary.set(scope.exit_node_id, scope);
  }
  const problems: RawProblem[] = [];
  for (const e of graph.edges) {
    if (nodeScope.get(e.source_node_id) === nodeScope.get(e.target_node_id)) continue;
    if (isSanctionedBoundaryEdge(e, entryBoundary, exitBoundary)) continue;
    problems.push(edge(e.id, "edge-crosses-scope"));
  }
  for (const { binding, ref } of outputReads(graph)) {
    if (nodeScope.get(ref.node_id) !== nodeScope.get(binding.target_node_id)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-crosses-scope"),
      );
    }
  }
  return problems;
}

function isSanctionedBoundaryEdge(
  e: WorkflowEdge,
  entryBoundary: Map<string, ScopeBoundary>,
  exitBoundary: Map<string, ScopeBoundary>,
): boolean {
  const entryScope = entryBoundary.get(e.source_node_id);
  if (entryScope !== undefined && e.source_port === entryScope.entry_port) return true;
  const exitScope = exitBoundary.get(e.source_node_id);
  return exitScope !== undefined && e.source_port === exitScope.exit_port;
}

// Rule 7 — no cycles.

export interface CycleResult {
  predecessors: Map<string, Set<string>>;
  order: string[] | null;
  problems: RawProblem[];
}

export function rule7NoCycles(graph: WorkflowGraph, nodeScope: Map<string, string>): CycleResult {
  const topLevelEdges = graph.edges.filter(
    (e) => !nodeScope.has(e.source_node_id) && !nodeScope.has(e.target_node_id),
  );
  const topLevelNodes = graph.nodes.filter((n) => !nodeScope.has(n.id)).map((n) => n.id);
  const { predecessors, order, cyclic } = kahn(topLevelNodes, topLevelEdges);
  const problems: RawProblem[] = [...cyclic].sort().map((nodeId) => node(nodeId, "node-in-cycle"));

  const scopeBodies = new Map<string, Set<string>>();
  for (const nodeId of nodeScope.keys()) {
    const scopeId = nodeScope.get(nodeId) as string;
    const body = scopeBodies.get(scopeId) ?? new Set<string>();
    body.add(nodeId);
    scopeBodies.set(scopeId, body);
  }
  for (const [, body] of scopeBodies) {
    const bodyEdges = graph.edges.filter(
      (e) => body.has(e.source_node_id) && body.has(e.target_node_id),
    );
    const { cyclic: bodyCyclic } = kahn([...body], bodyEdges);
    for (const nodeId of [...bodyCyclic].sort()) {
      problems.push(node(nodeId, "node-in-scope-cycle"));
    }
  }

  return { predecessors, order: cyclic.size > 0 ? null : order, problems };
}

// Rule 8 — no parallel fan-out (v1).

export function rule8NoParallelFanout(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  const byNode = new Map<string, Map<string, WorkflowEdge[]>>();
  for (const e of graph.edges) {
    const byPort = byNode.get(e.source_node_id) ?? new Map<string, WorkflowEdge[]>();
    const list = byPort.get(e.source_port) ?? [];
    list.push(e);
    byPort.set(e.source_port, list);
    byNode.set(e.source_node_id, byPort);
  }

  const problems: RawProblem[] = [];
  for (const [nodeId, byPort] of byNode) {
    const definition = definitionFor(definitions, nodeId);
    if (definition !== null && definition.kind === "control") continue;
    // A routed failure leaves by `error` instead of by the step's output, never beside it.
    const portsWithEdges = [...byPort.entries()].filter(
      ([port, edges]) => edges.length > 0 && port !== ERROR_PORT,
    );
    if (portsWithEdges.length > 1) problems.push(node(nodeId, "fanout-multiple-ports"));
    for (const [port, edges] of byPort) {
      if (edges.length > 1) {
        problems.push(node(nodeId, "fanout-port-multiple-edges", { port }));
      }
    }
  }
  return problems;
}

// Rule 9 — every required input bound exactly once.

export function rule9RequiredInputsBound(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  const problems: RawProblem[] = [];
  const boundCounts = new Map<string, number>();
  for (const binding of graph.bindings) {
    const key = `${binding.target_node_id}\u0000${binding.target_field}`;
    boundCounts.set(key, (boundCounts.get(key) ?? 0) + 1);
  }

  for (const [key, count] of boundCounts) {
    if (count > 1) {
      const separator = key.indexOf("\u0000");
      problems.push(
        nodeField(key.slice(0, separator), key.slice(separator + 1), "input-bound-twice"),
      );
    }
  }

  for (const n of graph.nodes) {
    const definition = definitionFor(definitions, n.id);
    if (definition === null) continue;
    for (const fieldName of requiredFields(definition.input_schema)) {
      const key = `${n.id}\u0000${fieldName}`;
      if ((boundCounts.get(key) ?? 0) === 0) {
        problems.push(nodeField(n.id, fieldName, "input-not-bound"));
      }
    }
    // A required setting - an agent, a table, the people to tell - left empty is
    // what the server's config check refuses first; a bindable one set by a
    // binding counts as set.
    for (const fieldName of requiredFields(definition.config_schema)) {
      const bound = (boundCounts.get(`${n.id}\u0000${fieldName}`) ?? 0) > 0;
      if (n.config[fieldName] === undefined && !bound) {
        problems.push(nodeField(n.id, fieldName, "config-not-set"));
      }
    }
  }
  return problems;
}

/**
 * The required fields of an `input_schema` — its JSON Schema `required` list, the
 * analog of a Pydantic field with no default reporting `is_required()`. An
 * all-optional model has no `required` key, which reads as no required fields.
 */
function requiredFields(schema: JsonSchema | null): string[] {
  const required = schema?.["required"];
  return Array.isArray(required)
    ? required.filter((name): name is string => typeof name === "string")
    : [];
}

/**
 * Rule 13 — names tell steps apart, and a step switched off leaves nothing
 * waiting on it: no two steps share a name (ignoring case), the trigger and a
 * step that decides the way stay on, and nothing reads a step that is off.
 */
export function rule13NamedAndSwitchedOffSteps(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  const problems: RawProblem[] = [];
  const named = new Set<string>();
  const off = new Set<string>();
  for (const n of graph.nodes) {
    const label = n.label?.trim() ?? "";
    if (label !== "") {
      const key = label.toLowerCase();
      if (named.has(key)) problems.push(node(n.id, "label-taken", { label }));
      else named.add(key);
    }
    if (n.disabled !== true) continue;
    off.add(n.id);
    if (n.id === graph.entry_node_id) problems.push(node(n.id, "trigger-switched-off"));
    else if (definitionFor(definitions, n.id)?.kind === "control") {
      problems.push(node(n.id, "control-switched-off"));
    }
  }
  for (const { binding, ref } of outputReads(graph)) {
    if (off.has(ref.node_id)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-reads-switched-off"),
      );
    }
  }
  return problems;
}
