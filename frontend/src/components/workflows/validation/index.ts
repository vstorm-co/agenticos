/**
 * The client-side mirror of #1786's graph validation — the single import point for
 * the editor's canvas, property panel and binding picker.
 *
 * `validateGraph` runs the structural rules (exactly-one-input,
 * reachable-outputs, type-compatibility, branch-local data availability, a merge's
 * branches, nested-scope boundaries, no cycles, one port per step), the parallel-branch
 * rules (legs that must all arrive, one answer per run, a Split's errors), plus
 * the required-inputs rule the property panel's binding form marks, and the two
 * resource checks a client can make without the server (a dangling reference, an
 * unknown definition version). It derives `scopes` from the graph's own topology
 * exactly as the backend does, so it never depends on a draft's stale scope claim.
 *
 * It is **deliberately non-authoritative**: publish always re-validates
 * server-side against `app/workflows/graph/validate.py`, and drift degrades to a
 * worse editing experience, never a correctness bug, since nothing client-side
 * executes. What the backend checks and the client cannot — the graph size ceiling,
 * granted scopes, `config` against its schema, a `TableIORef`'s liveness, a literal
 * value's type, a binding's target-field existence — stays the server's, and the
 * drift fixtures document exactly which cases are excluded and why.
 *
 * The type-compatibility helpers ({@link portShapesCompatible},
 * {@link resolveFieldType}, {@link fieldType}, {@link typesCompatible}) and the
 * reachability helpers ({@link computePrecede}, {@link availableSourceNodes})
 * are exported for the binding picker: its candidate list *is* rule 4's precede
 * set filtered by rule 3's compatibility.
 */

import type { NodeCatalog, WorkflowGraph } from "@/lib/workflows/types";

import {
  danglingReferences,
  missingVersions,
  rule1SingleEntry,
  rule2ReachableOutputs,
  rule3TypeCompatibility,
  templateTargets,
  rule4BranchLocalAvailability,
  portNameClashes,
  quickLogProblems,
  rule5ExclusiveMerge,
  rule6NestedScopeBoundaries,
  rule7NoCycles,
  mergeSettingBindingProblems,
  rule8OnePort,
  rule9RequiredInputsBound,
  rule13NamedAndSwitchedOffSteps,
  mergeModeProblems,
  splitProblems,
  sharedErrorHandlerProblems,
  errorRoutingProblems,
  answeringStepProblems,
} from "./rules";
import { analyse } from "./joins";
import { deriveScopes, nodeScopeMap, resolveDefinitions } from "./topology";
import { MESSAGE_KEYS, type RawProblem, type ValidationTranslator } from "./types";

export { UNKNOWN } from "./schema";
export type { ResolvedType } from "./schema";
export {
  portShapesCompatible,
  portSchema,
  outputFieldNames,
  resolveFieldType,
  fieldType,
  isDynamic,
  typesCompatible,
  schemaTypeToken,
} from "./schema";
export { deriveScopes, resolveDefinitions } from "./topology";
export type { ValidationCode, ValidationTranslator } from "./types";
export { MESSAGE_KEYS } from "./types";

/**
 * One client-side validation problem, field / edge / node-scoped the same way the
 * server's `GraphValidationError` is — so the property panel shows a per-field
 * message, the canvas highlights an offending edge, and the footer collects them
 * all into a problems list.
 */
export interface ValidationProblem {
  /** The offending node, or null for a graph-level or edge-scoped problem. */
  nodeId: string | null;
  /** The offending edge, or null. */
  edgeId: string | null;
  /** The offending field (a `Binding.target_field` path), or null. */
  field: string | null;
  /** A stable code mirroring the server rule, for grouping and links. */
  code: string;
  /** Already-translated, human-readable text. */
  message: string;
}

function render(problem: RawProblem, t: ValidationTranslator): ValidationProblem {
  return {
    nodeId: problem.nodeId,
    edgeId: problem.edgeId,
    field: problem.field,
    code: problem.code,
    message: t(MESSAGE_KEYS[problem.code], problem.params),
  };
}

/**
 * Validate a graph against the client-side mirror of #1786's rules.
 *
 * @param graph The in-memory graph the editor holds.
 * @param catalog The node catalog, for resolving definitions, schemas and scope
 *   ownership. The stub signature took only a graph; the rules genuinely need the
 *   catalog, so it is a required second argument.
 * @param t A translator for the top-level `workflows` namespace — the caller's
 *   `useTranslations("workflows")`. Kept out of the rules so they stay pure; only
 *   the final message rendering calls it.
 * @returns Every problem found, collected together the way the server collects
 *   them — never the first alone.
 */
export function validateGraph(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
  t: ValidationTranslator,
): ValidationProblem[] {
  const definitions = resolveDefinitions(graph, catalog);
  const scopes = deriveScopes(graph, definitions);

  // Every later rule assumes an edge or binding names a real node; a dangling
  // reference is refused on its own, ahead of them, exactly as the server does.
  const dangling = danglingReferences(graph);
  if (dangling.length > 0) return dangling.map((problem) => render(problem, t));

  const nodeScope = nodeScopeMap(scopes);
  const cycle = rule7NoCycles(graph, nodeScope);
  const analysis = analyse(graph, definitions, nodeScope, cycle.order !== null);

  const problems: RawProblem[] = [
    ...missingVersions(graph, definitions),
    ...cycle.problems,
    ...rule1SingleEntry(graph, definitions),
    ...rule2ReachableOutputs(graph, nodeScope),
    ...rule3TypeCompatibility(graph, definitions),
    ...templateTargets(graph, definitions),
    ...rule4BranchLocalAvailability(graph, analysis.precede),
    ...mergeModeProblems(analysis),
    ...rule5ExclusiveMerge(analysis),
    ...portNameClashes(graph, definitions),
    ...quickLogProblems(graph, definitions),
    ...rule6NestedScopeBoundaries(graph, scopes, nodeScope),
    ...rule8OnePort(graph, definitions),
    ...errorRoutingProblems(graph, definitions),
    ...sharedErrorHandlerProblems(analysis),
    ...answeringStepProblems(analysis),
    ...splitProblems(graph, definitions),
    ...mergeSettingBindingProblems(graph, definitions),
    ...rule9RequiredInputsBound(graph, definitions),
    ...rule13NamedAndSwitchedOffSteps(graph, definitions),
  ];
  return problems.map((problem) => render(problem, t));
}

/**
 * What must have run before each step does - the steps before it that run whenever it
 * does: what dominates it and every leg of a parallel group before the step that waits
 * for them, but not one arm of an If. What a
 * binding may read: the picker's candidate list *is* this set filtered by rule 3's
 * compatibility. Empty when the outer graph has a cycle or the entry is not a real
 * node, matching the server.
 */
export function computePrecede(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
): Map<string, Set<string>> {
  const definitions = resolveDefinitions(graph, catalog);
  const scopes = deriveScopes(graph, definitions);
  const nodeScope = nodeScopeMap(scopes);
  const cycle = rule7NoCycles(graph, nodeScope);
  return analyse(graph, definitions, nodeScope, cycle.order !== null).precede;
}

/**
 * The nodes whose output a binding on `targetNodeId` may read: every node that must
 * precede it, excluding the target itself (rule 4 forbids a node reading its own
 * output). The binding picker filters these further by rule 3 compatibility.
 */
export function availableSourceNodes(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
  targetNodeId: string,
): Set<string> {
  const precede = computePrecede(graph, catalog).get(targetNodeId);
  if (precede === undefined) return new Set();
  const available = new Set(precede);
  available.delete(targetNodeId);
  return available;
}
