/**
 * The structural rules (plus the required-inputs rule the property panel
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
  canQuickLog,
  outputRefs,
  type Binding,
  type JsonSchema,
  type NodeInstance,
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
import { AUTHOR_NAMED_PORTS, ERROR_PORT, routesErrors } from "@/lib/workflows/ports";
import { isTrigger, entryNodes, UNATTENDED_TRIGGERS } from "@/lib/workflows/triggers";
import {
  anyPairRunsTogether,
  canRunTogether,
  wireCondition,
  wireRunsWhenever,
  type GraphAnalysis,
  type JoinWire,
} from "./joins";
import { definitionFor, forwardEdges, kahn, nodeIds, type DefinitionMap } from "./topology";
import type { RawProblem } from "./types";

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
  const seen = new Set<string>();
  const problems: RawProblem[] = [];
  for (const node of graph.nodes.filter((n) => isTrigger(definitionFor(definitions, n.id)))) {
    if (incoming.has(node.id)) problems.push(nodeField(node.id, "", "entry-is-edge-target"));
    if (UNATTENDED_TRIGGERS.has(node.definition_id) && seen.has(node.definition_id))
      problems.push(nodeField(node.id, "", "trigger-not-entry"));
    seen.add(node.definition_id);
  }
  return problems;
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
  const queue: string[] = entryNodes(graph).map((node) => node.id);
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

// Rule 4 — branch-local data availability: what must precede a step (`GraphAnalysis.precede`).

export function rule4BranchLocalAvailability(
  graph: WorkflowGraph,
  precede: Map<string, Set<string>>,
): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const { binding, ref } of outputReads(graph)) {
    const sourceId = ref.node_id;
    const targetId = binding.target_node_id;
    if (sourceId === targetId) {
      problems.push(nodeField(targetId, binding.target_field, "binding-self-reference"));
      continue;
    }
    const targetPrecede = precede.get(targetId);
    if (targetPrecede === undefined) continue;
    if (!targetPrecede.has(sourceId)) {
      problems.push(nodeField(targetId, binding.target_field, "binding-unavailable"));
    }
  }
  return problems;
}

/**
 * An author-named output that reuses a port its step has - the static ones, the
 * `unsure` of a classifier with a minimum confidence, the `error` of a step that
 * routes its errors. The analog of `nodes/_port_names.py` and
 * `_error_port_clash_problems`; the problem sits on the entry's name field.
 */
export function portNameClashes(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const n of graph.nodes) {
    const definition = definitionFor(definitions, n.id);
    const named = definition === null ? undefined : AUTHOR_NAMED_PORTS[definition.id];
    const entries = named === undefined ? undefined : n.config[named.list];
    if (named === undefined || !Array.isArray(entries)) continue;
    const taken = new Set(named.static);
    if (routesErrors(n)) taken.add(ERROR_PORT);
    if (definition?.id === "ai.classify" && typeof n.config.min_confidence === "number") {
      taken.add("unsure");
    }
    entries.forEach((entry, index) => {
      const name = typeof entry === "object" && entry !== null ? entry[named.key] : undefined;
      if (typeof name !== "string" || !taken.has(name)) return;
      problems.push({
        nodeId: n.id,
        edgeId: null,
        field: `${named.list}/${index}/${named.key}`,
        code: "port-name-taken",
        params: { name },
      });
    });
  }
  return problems;
}

/** A reference in a quick log message, as the server reads it. */
const QUICK_LOG_REFERENCE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}/g;

/**
 * What a quick log may not say - the analog of `_quick_log_problems`: it goes on
 * a loop itself, not its item or yield step; `outputs` is never empty and names
 * only the step's own outputs (`error` when it routes errors); and a message reads
 * nothing of an error but its code and message.
 */
export function quickLogProblems(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const n of graph.nodes) {
    const quickLog = n.quick_log;
    if (quickLog == null) continue;
    if (!canQuickLog(n.definition_id)) {
      problems.push({
        nodeId: n.id,
        edgeId: null,
        field: "quick_log",
        code: "quick-log-not-here",
      });
      continue;
    }
    for (const [, reference] of quickLog.message.matchAll(QUICK_LOG_REFERENCE)) {
      const path = (reference as string).split(".");
      if (path[0] === "error" && !(path.length === 2 && ["code", "message"].includes(path[1]!))) {
        problems.push({
          nodeId: n.id,
          edgeId: null,
          field: "quick_log/message",
          code: "quick-log-error-reference",
          params: { reference: reference as string },
        });
      }
    }
    const logged = quickLog.outputs;
    if (logged == null) continue;
    if (logged.length === 0) {
      problems.push({
        nodeId: n.id,
        edgeId: null,
        field: "quick_log/outputs",
        code: "quick-log-no-outputs",
      });
    }
    const definition = definitionFor(definitions, n.id);
    if (definition === null) continue;
    const have = new Set(
      definition.ports.filter((port) => port.kind === "output").map((port) => port.id),
    );
    logged.forEach((name, index) => {
      if (have.has(name)) return;
      problems.push({
        nodeId: n.id,
        edgeId: null,
        field: `quick_log/outputs/${index}`,
        code: "quick-log-output-unknown",
        params: { name },
      });
    });
  }
  return problems;
}

// Rule 5 — a merge takes one edge from each branch.

const MERGE = "logic.merge";
const SPLIT = "logic.split";

/** A merge's `wait_for` as stored: absent means the branch that ran. */
function waitFor(n: NodeInstance): "one" | "all" {
  return n.config.wait_for === "all" ? "all" : "one";
}

function merges(graph: WorkflowGraph, definitions: DefinitionMap): NodeInstance[] {
  return graph.nodes.filter((n) => definitionFor(definitions, n.id)?.id === MERGE);
}

/**
 * Whether a merge's branches are exclusive is the join classification's to say
 * ({@link mergeModeProblems}); what is left here is the shape no classification can
 * read - two edges leaving one port into the same merge, whichever way it waits. The analog of
 * `_rule_5_exclusive_merge`.
 */
export function rule5ExclusiveMerge(analysis: GraphAnalysis): RawProblem[] {
  const { graph, definitions } = analysis;
  const problems: RawProblem[] = [];
  for (const n of merges(graph, definitions)) {
    const edgesIn = graph.edges.filter((e) => e.target_node_id === n.id);
    const distinct = new Set(edgesIn.map((e) => `${e.source_node_id}\u0000${e.source_port}`));
    if (edgesIn.length > 1 && distinct.size !== edgesIn.length) {
      problems.push(node(n.id, "merge-duplicate-branch"));
    }
  }
  return problems;
}

const SLUG_LIMIT = 32;

function slug(text: string): string {
  const cleaned = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return (/^[0-9]/.test(cleaned) ? `b_${cleaned}` : cleaned).slice(0, SLUG_LIMIT);
}

/**
 * The name of each branch reaching a merge, by `source\0port`: the stored key where
 * the config has one, else the Split's branch name when the wire leaves a Split, else
 * a slug of the source step's name. The analog of `logic_merge.branch_keys`.
 */
export function branchKeys(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
  merge: NodeInstance,
): Map<string, string> {
  const configured = merge.config.branch_keys;
  const stored = new Map<string, unknown>();
  for (const item of Array.isArray(configured) ? configured : []) {
    if (typeof item === "object" && item !== null) {
      stored.set(`${item.source_node_id}\u0000${item.source_port}`, item.key);
    }
  }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const keys = new Map<string, string>();
  for (const e of graph.edges) {
    const source = byId.get(e.source_node_id);
    const wire = `${e.source_node_id}\u0000${e.source_port}`;
    if (e.target_node_id !== merge.id || source === undefined || keys.has(wire)) continue;
    const key = stored.get(wire);
    if (typeof key === "string") keys.set(wire, key);
    else if (source.definition_id === SPLIT) keys.set(wire, e.source_port);
    else {
      const name = source.label ? source.label : definitionFor(definitions, source.id)?.name;
      keys.set(wire, slug(name ?? source.definition_id));
    }
  }
  return keys;
}

/**
 * A merge's `wait_for` must match how its branches reach it, and its branch names be
 * usable: branches that can run together need `all`, and `all` needs each of them
 * certain to arrive whenever the merge runs; branches of which only one runs need `one`.
 * Under `all` the names differ, and a name read that no branch has is refused where it
 * is read. A merge with a branch nothing reaches is left to the reachability rule. The
 * analog of `_merge_mode_problems`.
 */
export function mergeModeProblems(analysis: GraphAnalysis): RawProblem[] {
  const { graph, definitions } = analysis;
  const problems: RawProblem[] = [];
  const keysByMerge = new Map<string, Set<string>>();
  for (const n of merges(graph, definitions)) {
    const mode = waitFor(n);
    const keys = branchKeys(graph, definitions, n);
    const keyOf = (wire: JoinWire): string =>
      keys.get(`${wire.sourceNodeId}\u0000${wire.sourcePort}`) as string;
    const wires = analysis.incoming.get(n.id) ?? [];
    if (wires.length > 1 && wires.every((w) => wireCondition(analysis, n.id, w) !== undefined)) {
      const together = anyPairRunsTogether(analysis, n.id);
      const uncertain = wires.filter((w) => !wireRunsWhenever(analysis, n.id, w));
      const [first] = uncertain;
      if (mode === "one" && together) {
        problems.push(
          first === undefined
            ? node(n.id, "merge-wait-for-all")
            : node(n.id, "merge-together-uncertain", { name: keyOf(first) }),
        );
      } else if (mode === "all" && !together) {
        problems.push(node(n.id, "merge-wait-for-one"));
      } else if (mode === "all") {
        for (const wire of uncertain) {
          problems.push(node(n.id, "merge-leg-not-guaranteed", { name: keyOf(wire) }));
        }
      }
    }
    const names = [...keys.values()];
    keysByMerge.set(n.id, new Set(names));
    if (
      mode === "all" &&
      (names.some((name) => name === "") || new Set(names).size !== names.length)
    ) {
      problems.push(nodeField(n.id, "branch_keys", "merge-key-invalid"));
    }
  }
  for (const { binding, ref } of outputReads(graph)) {
    const keys = keysByMerge.get(ref.node_id);
    const [head, key] = ref.field_path;
    if (keys === undefined || head !== "branches" || key === undefined || keys.has(key)) continue;
    problems.push({
      nodeId: binding.target_node_id,
      edgeId: null,
      field: binding.target_field,
      code: "merge-key-unknown",
      params: { key },
    });
  }
  return problems;
}

/** A Split takes every branch at once, so it has no one way out for an error to take instead. */
export function splitProblems(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  return graph.nodes
    .filter((n) => routesErrors(n) && definitionFor(definitions, n.id)?.id === SPLIT)
    .map((n) => nodeField(n.id, "policy", "split-routes-errors"));
}

const MERGE_SETTINGS = new Set(["wait_for", "branch_keys"]);

/**
 * A Merge's `wait_for` and `branch_keys` are fixed in the editor, never bound: the
 * executor decides when a Merge runs from its stored config, so a binding would reach
 * the handler's call but not that decision.
 */
export function mergeSettingBindingProblems(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  return graph.bindings
    .filter(
      (b) =>
        definitionFor(definitions, b.target_node_id)?.id === MERGE &&
        MERGE_SETTINGS.has(b.target_field.replace(/\/.*$/, "")),
    )
    .map((b) => nodeField(b.target_node_id, b.target_field, "merge-setting-bound"));
}

/**
 * A failure a graph claims to handle must reach a handler: a step routing its errors
 * needs its `error` port wired, and an error handler its `default` - the mirror of the
 * server's rule 10 node checks.
 */
export function errorRoutingProblems(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
): RawProblem[] {
  const wired = (nodeId: string, port: string) =>
    graph.edges.some((e) => e.source_node_id === nodeId && e.source_port === port);
  const problems: RawProblem[] = [];
  for (const n of graph.nodes) {
    if (routesErrors(n) && !wired(n.id, ERROR_PORT))
      problems.push(node(n.id, "error-port-unwired"));
    if (definitionFor(definitions, n.id)?.id === "error.handle" && !wired(n.id, "default")) {
      problems.push(node(n.id, "error-handler-default-unwired"));
    }
  }
  return problems;
}

/** An error handler may not be fed by two branches that run together. */
export function sharedErrorHandlerProblems(analysis: GraphAnalysis): RawProblem[] {
  return analysis.graph.nodes
    .filter(
      (n) =>
        definitionFor(analysis.definitions, n.id)?.id === "error.handle" &&
        anyPairRunsTogether(analysis, n.id),
    )
    .map((n) => node(n.id, "error-handler-shared"));
}

const ANSWERING: [string, RawProblem["code"]][] = [
  ["core.output", "outputs-both-run"],
  ["webhook.respond", "respond-both-run"],
];

/** A run answers once, and a webhook is answered once: no second step that may answer too. */
export function answeringStepProblems(analysis: GraphAnalysis): RawProblem[] {
  const problems: RawProblem[] = [];
  for (const [definitionId, code] of ANSWERING) {
    const answering = analysis.graph.nodes.filter(
      (n) => definitionFor(analysis.definitions, n.id)?.id === definitionId,
    );
    answering.forEach((later, index) => {
      const clash = answering
        .slice(0, index)
        .some(
          (earlier) =>
            analysis.nodeScope.get(earlier.id) === analysis.nodeScope.get(later.id) &&
            canRunTogether(analysis, earlier.id, later.id),
        );
      if (clash) problems.push(node(later.id, code));
    });
  }
  return problems;
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
  order: string[] | null;
  problems: RawProblem[];
}

export function rule7NoCycles(graph: WorkflowGraph, nodeScope: Map<string, string>): CycleResult {
  const topLevelEdges = graph.edges.filter(
    (e) => !nodeScope.has(e.source_node_id) && !nodeScope.has(e.target_node_id),
  );
  const topLevelNodes = graph.nodes.filter((n) => !nodeScope.has(n.id)).map((n) => n.id);
  const { order, cyclic } = kahn(topLevelNodes, topLevelEdges);
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

  return { order: cyclic.size > 0 ? null : order, problems };
}

// Rule 8 — one port.

/**
 * A step that is not a control node sends its output through one port. Any number of
 * steps may follow a port: they run side by side, and the steps waiting for them are
 * what `mergeModeProblems` judges.
 */
export function rule8OnePort(graph: WorkflowGraph, definitions: DefinitionMap): RawProblem[] {
  // A routed failure leaves by `error` instead of by the step's output, never beside it.
  const portsByNode = new Map<string, Set<string>>();
  for (const e of graph.edges) {
    if (e.source_port === ERROR_PORT) continue;
    const ports = portsByNode.get(e.source_node_id) ?? new Set<string>();
    ports.add(e.source_port);
    portsByNode.set(e.source_node_id, ports);
  }
  const problems: RawProblem[] = [];
  for (const [nodeId, ports] of portsByNode) {
    if (definitionFor(definitions, nodeId)?.kind === "control") continue;
    if (ports.size > 1) problems.push(node(nodeId, "fanout-multiple-ports"));
  }
  return problems;
}

// Rule 9 — every required input bound exactly once.

/** Steps that branch on `value`; unbound it reads null, so an If takes `false` and a Switch `otherwise`, silently. */
const DECIDES_ON_VALUE: ReadonlySet<string> = new Set(["logic.if", "logic.switch"]);

/** Whether a binding targets the node's `value`, whole or by key. */
function valueBound(graph: WorkflowGraph, nodeId: string): boolean {
  return graph.bindings.some(
    (b) =>
      b.target_node_id === nodeId &&
      (b.target_field === "value" || b.target_field.startsWith("value/")),
  );
}

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
    if (DECIDES_ON_VALUE.has(definition.id) && !valueBound(graph, n.id)) {
      problems.push(nodeField(n.id, "value", "decision-value-not-bound"));
    }
    for (const fieldName of requiredFields(definition.input_schema)) {
      const key = `${n.id}\u0000${fieldName}`;
      if ((boundCounts.get(key) ?? 0) === 0) {
        problems.push(nodeField(n.id, fieldName, "input-not-bound"));
      }
    }
    if (definition.id === "agent.run" && !n.config.inline) {
      const agent = n.config.agent;
      if (
        typeof agent !== "object" ||
        agent === null ||
        !("agent_id" in agent) ||
        typeof agent.agent_id !== "string" ||
        !("version_id" in agent) ||
        typeof agent.version_id !== "string"
      ) {
        problems.push(nodeField(n.id, "agent", "config-not-set"));
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
 * Whether a step switched off hands on what `ref` reads from it: what comes in
 * through its one incoming edge, from a step that is on, has that field, of a
 * type the step's own output declares there. The analog of `_hands_on`.
 */
function handsOn(graph: WorkflowGraph, definitions: DefinitionMap, ref: NodeOutputRef): boolean {
  const incoming = graph.edges.filter((edge) => edge.target_node_id === ref.node_id);
  const edge = incoming[0];
  if (incoming.length !== 1 || edge === undefined) return false;
  const before = graph.nodes.find((candidate) => candidate.id === edge.source_node_id);
  const arrivingFrom = definitionFor(definitions, edge.source_node_id);
  const own = definitionFor(definitions, ref.node_id);
  if (before?.disabled === true || arrivingFrom === null || own === null) return false;
  return typesCompatible(
    resolveFieldType(arrivingFrom, edge.source_port, ref.field_path),
    resolveFieldType(own, ref.port, ref.field_path),
  );
}

/**
 * Rule 13 — names tell steps apart, and a step switched off leaves nothing
 * waiting on it: no two steps share a name (ignoring case), the trigger and a
 * step that decides the way stay on, and nothing reads a step that is off -
 * unless what comes into it has the field read, which it hands on instead.
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
    if (off.has(ref.node_id) && !handsOn(graph, definitions, ref)) {
      problems.push(
        nodeField(binding.target_node_id, binding.target_field, "binding-reads-switched-off"),
      );
    }
  }
  return problems;
}
