/**
 * The binding half of the property form — pure, so every branch is unit-testable
 * without React.
 *
 * Two jobs:
 *
 * 1. **Candidate sources for the binding picker.** A `BindingField` in binding
 *    mode offers every upstream `(node, output port)` a value may be read from.
 *    That set *is* rule 4's reachability ({@link availableSourceNodes}) filtered by
 *    rule 3's type compatibility ({@link typesCompatible}), both taken from the
 *    validation mirror so the picker and the validator never disagree.
 *
 * 2. **Rebasing a binding's `target_field` path** when a repeatable-row array is
 *    reordered or a row is removed, or a union branch is switched. A binding on a
 *    nested leaf carries a JSON-Pointer path (`mappings/0/value`); moving row 0 to
 *    row 1 has to move that binding too, or it silently targets the wrong row.
 */

import {
  availableSourceNodes,
  outputFieldNames,
  resolveDefinitions,
  resolveFieldType,
  schemaTypeToken,
  typesCompatible,
  type ResolvedType,
} from "@/components/workflows/validation";
import {
  bindingFieldPath,
  nodeDisplayName,
  parseBindingFieldPath,
  type Binding,
  type NodeCatalog,
  type NodeDefinition,
  type Uuid,
  type WorkflowGraph,
} from "@/lib/workflows/types";

import { unwrapOptional, type Schema } from "./schema-model";

/** The current binding on one field, or undefined when nothing targets it. */
export function bindingFor(
  bindings: readonly Binding[],
  targetNodeId: Uuid,
  targetField: string,
): Binding | undefined {
  return bindings.find(
    (binding) => binding.target_node_id === targetNodeId && binding.target_field === targetField,
  );
}

/** The literal value a binding carries, or undefined when it is not a literal. */
export function literalValueOf(binding: Binding | undefined): unknown {
  return binding !== undefined && binding.source.kind === "literal"
    ? binding.source.value
    : undefined;
}

/** Whether a binding reads another node's output (binding mode), not a literal. */
export function isNodeOutput(binding: Binding | undefined): boolean {
  return binding !== undefined && binding.source.kind === "node_output";
}

/** A binding that stores a typed-in literal on one field. */
export function literalBinding(targetNodeId: Uuid, targetField: string, value: unknown): Binding {
  return {
    target_node_id: targetNodeId,
    target_field: targetField,
    source: { kind: "literal", value },
  };
}

/**
 * A binding that reads one upstream node's output port - or one field inside it,
 * when `fieldPath` is given - into one field.
 */
export function nodeOutputBinding(
  targetNodeId: Uuid,
  targetField: string,
  nodeId: Uuid,
  port: string,
  fieldPath: readonly string[] = [],
): Binding {
  return {
    target_node_id: targetNodeId,
    target_field: targetField,
    source: { kind: "node_output", node_id: nodeId, port, field_path: [...fieldPath] },
  };
}

/** How a candidate `(node, port)` is keyed as one `Select` value, and split back. */
const CANDIDATE_SEP = "::";

/**
 * The `Select` value naming one candidate source: `node::port` for a whole output
 * port, with `::` and the URI-encoded, `/`-joined field path appended for a field
 * inside it.
 */
export function candidateKey(
  nodeId: Uuid,
  port: string,
  fieldPath: readonly string[] = [],
): string {
  const whole = `${nodeId}${CANDIDATE_SEP}${port}`;
  if (fieldPath.length === 0) return whole;
  return `${whole}${CANDIDATE_SEP}${fieldPath.map(encodeURIComponent).join("/")}`;
}

/**
 * One offered binding source - an upstream node's output port, or a field inside it,
 * type-compatible with the target field.
 */
export interface SourceCandidate {
  /** The `Select` value - `(node, port, field path)` encoded. */
  key: string;
  nodeId: Uuid;
  port: string;
  /** The field inside the port, or empty when the candidate is the whole port. */
  fieldPath: string[];
  /** The source node's catalog name, disambiguated by a short id. */
  nodeLabel: string;
  /** The output port's own label. */
  portLabel: string;
  /** The declared type of the port or field, shown to disambiguate same-named ports. */
  typeToken: string;
}

/** How deep into a nested output the picker offers fields; deeper is left to the schema. */
const MAX_FIELD_DEPTH = 3;

/** Every field path under an output port, depth first, down to {@link MAX_FIELD_DEPTH}. */
function outputFieldPaths(
  definition: NodeDefinition,
  portId: string,
  prefix: readonly string[] = [],
): string[][] {
  if (prefix.length >= MAX_FIELD_DEPTH) return [];
  return outputFieldNames(definition, portId, prefix).flatMap((name) => {
    const path = [...prefix, name];
    return [path, ...outputFieldPaths(definition, portId, path)];
  });
}

/**
 * Every upstream output a field may bind to: the nodes that dominate the target
 * (rule 4), each output port - and each field inside one - whose declared type
 * matches the field's (rule 3). A port comes before its fields, and graph order is
 * preserved so the list is stable across renders.
 *
 * Fields are offered because most ports carry an object while most inputs are
 * scalars: a string input could never be bound to `debug.echo`'s `out` as a whole,
 * only to its `echoed` field.
 */
export function sourceCandidates(
  graph: WorkflowGraph,
  catalog: NodeCatalog,
  targetNodeId: Uuid,
  targetSchema: Schema,
): SourceCandidate[] {
  const available = availableSourceNodes(graph, catalog, targetNodeId);
  const definitions = resolveDefinitions(graph, catalog);
  const target = unwrapOptional(targetSchema) as ResolvedType;
  const candidates: SourceCandidate[] = [];
  for (const node of graph.nodes) {
    if (!available.has(node.id)) continue;
    const definition = definitions.get(node.id);
    if (definition === undefined || definition === null) continue;
    for (const port of definition.ports) {
      if (port.kind !== "output") continue;
      for (const fieldPath of [[], ...outputFieldPaths(definition, port.id)]) {
        const sourceType = resolveFieldType(definition, port.id, fieldPath);
        if (!typesCompatible(sourceType, target)) continue;
        candidates.push({
          key: candidateKey(node.id, port.id, fieldPath),
          nodeId: node.id,
          port: port.id,
          fieldPath,
          nodeLabel: nodeDisplayName(definition.name, node.id, true),
          portLabel: port.label,
          typeToken: schemaTypeToken(sourceType),
        });
      }
    }
  }
  return candidates;
}

/** A candidate resolved from a `Select` value, or undefined when none matches. */
export function candidateByKey(
  candidates: readonly SourceCandidate[],
  key: string,
): SourceCandidate | undefined {
  return candidates.find((candidate) => candidate.key === key);
}

// Rebasing nested bindings when rows move.

/** The removals and re-writes one structural edit implies for the flat binding list. */
export interface BindingRebase {
  /** `target_field`s to drop (their row went away, or they moved). */
  toRemove: string[];
  /** Bindings to write at their new `target_field`. */
  toUpsert: Binding[];
}

/** The row index a binding sits at directly under `prefix`, or null when it is not under it. */
function rowIndexUnder(field: string, prefix: readonly string[]): number | null {
  const segments = parseBindingFieldPath(field);
  if (segments.length <= prefix.length) return null;
  for (let i = 0; i < prefix.length; i += 1) {
    if (segments[i] !== prefix[i]) return null;
  }
  const index = segments[prefix.length] as string;
  return /^\d+$/.test(index) ? Number(index) : null;
}

/** A field with the row index directly under `prefix` rewritten to `next`. */
function withRowIndex(field: string, prefix: readonly string[], next: number): string {
  const segments = parseBindingFieldPath(field);
  segments[prefix.length] = String(next);
  return bindingFieldPath(segments);
}

/** Whether a field is strictly nested under `prefix` (deeper, same head). */
function isStrictlyUnder(field: string, prefix: readonly string[]): boolean {
  const segments = parseBindingFieldPath(field);
  if (segments.length <= prefix.length) return false;
  return prefix.every((segment, i) => segments[i] === segment);
}

/**
 * The rebase for removing row `removedIndex` of the array at `prefix`: drop every
 * binding in that row, and shift every binding in a later row down by one.
 */
export function rebaseRemove(
  bindings: readonly Binding[],
  targetNodeId: Uuid,
  prefix: readonly string[],
  removedIndex: number,
): BindingRebase {
  const rebase: BindingRebase = { toRemove: [], toUpsert: [] };
  for (const binding of bindings) {
    if (binding.target_node_id !== targetNodeId) continue;
    const index = rowIndexUnder(binding.target_field, prefix);
    if (index === null || index < removedIndex) continue;
    rebase.toRemove.push(binding.target_field);
    if (index > removedIndex) {
      rebase.toUpsert.push({
        ...binding,
        target_field: withRowIndex(binding.target_field, prefix, index - 1),
      });
    }
  }
  return rebase;
}

/** The rebase for swapping rows `a` and `b` of the array at `prefix`. */
export function rebaseSwap(
  bindings: readonly Binding[],
  targetNodeId: Uuid,
  prefix: readonly string[],
  a: number,
  b: number,
): BindingRebase {
  const rebase: BindingRebase = { toRemove: [], toUpsert: [] };
  for (const binding of bindings) {
    if (binding.target_node_id !== targetNodeId) continue;
    const index = rowIndexUnder(binding.target_field, prefix);
    if (index !== a && index !== b) continue;
    const next = index === a ? b : a;
    rebase.toRemove.push(binding.target_field);
    rebase.toUpsert.push({
      ...binding,
      target_field: withRowIndex(binding.target_field, prefix, next),
    });
  }
  return rebase;
}

/** The rebase for clearing every binding nested under `prefix` (a union branch switch). */
export function rebaseClear(
  bindings: readonly Binding[],
  targetNodeId: Uuid,
  prefix: readonly string[],
): BindingRebase {
  const toRemove = bindings
    .filter(
      (binding) =>
        binding.target_node_id === targetNodeId && isStrictlyUnder(binding.target_field, prefix),
    )
    .map((binding) => binding.target_field);
  return { toRemove, toUpsert: [] };
}

/** Apply a rebase through the store's per-binding actions — removals first, then writes. */
export function applyRebase(
  rebase: BindingRebase,
  targetNodeId: Uuid,
  upsert: (binding: Binding) => void,
  remove: (targetNodeId: Uuid, targetField: string) => void,
): void {
  for (const field of rebase.toRemove) remove(targetNodeId, field);
  for (const binding of rebase.toUpsert) upsert(binding);
}
