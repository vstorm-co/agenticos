import { type NodeOutputRef, outputRefs } from "./types";
import type { BindingSource, NodeInstance, Uuid, WorkflowGraph } from "./types";

/** A merge branch that kept its wire but got a new name. */
export interface MergeKeyRename {
  from: string;
  to: string;
}

const MERGE = "logic.merge";

function keyEntries(config: Record<string, unknown>): Record<string, unknown>[] | null {
  const entries = config.branch_keys;
  if (!Array.isArray(entries)) return null;
  return entries.map((entry) =>
    typeof entry === "object" && entry !== null ? (entry as Record<string, unknown>) : {},
  );
}

/** Every branch name a binding or template of `graph` reads from the merge's `branches`. */
function readKeys(graph: WorkflowGraph, mergeId: Uuid): Set<string> {
  const names = new Set<string>();
  for (const { source } of graph.bindings) {
    for (const ref of outputRefs(source)) {
      const [head, key] = ref.field_path;
      if (ref.node_id === mergeId && head === "branches" && key !== undefined) names.add(key);
    }
  }
  return names;
}

const wireOf = (entry: Record<string, unknown>): string =>
  `${String(entry.source_node_id)}\u0000${String(entry.source_port)}`;

/**
 * The one branch name an edit to a merge's config renamed, or null. Entries are matched
 * by the wire they name, not by position, so a deleted or added leg does not stop the
 * carry: the rename is the one entry whose stored key changed, to a name that is not
 * blank and not another branch's.
 *
 * As with a port, every keystroke is an edit, so a name cleared and retyped leaves the
 * old name blank: the rename then continues from the one name the graph still reads
 * from this merge that is no longer one of its keys.
 *
 * An entry the config did not store before is a default name: it counts as unchanged
 * unless nothing else changed and it is the one new name nothing reads, while exactly
 * one name that is read has no branch left - then that is the rename. That is how a
 * merge whose keys were never stored (a hand-built one) carries its first rename.
 * With a different mode in the edit, or more than one candidate, nothing is carried.
 */
export function mergeKeyRename(
  before: NodeInstance,
  nextConfig: Record<string, unknown>,
  graph: WorkflowGraph,
): MergeKeyRename | null {
  if (before.definition_id !== MERGE) return null;
  const next = keyEntries(nextConfig);
  if (next === null) return null;
  const stored = new Map(
    (keyEntries(before.config) ?? []).map((entry) => [wireOf(entry), entry.key]),
  );
  const nextKeys = new Set(next.map((entry) => entry.key));
  const orphans = () => [...readKeys(graph, before.id)].filter((key) => !nextKeys.has(key));
  const only = <T>(list: T[]): T | null => (list.length === 1 ? (list[0] as T) : null);

  const changed = next.filter(
    (entry) => stored.has(wireOf(entry)) && stored.get(wireOf(entry)) !== entry.key,
  );
  if (changed.length > 1) return null;
  const entry = changed[0];
  if (entry !== undefined) {
    const to = entry.key;
    if (typeof to !== "string" || to === "") return null;
    if (next.some((other) => other !== entry && other.key === to)) return null;
    const was = stored.get(wireOf(entry));
    if (typeof was === "string" && was !== "") return { from: was, to };
    const from = only(orphans());
    return from === null ? null : { from, to };
  }
  if (before.config.wait_for !== nextConfig.wait_for) return null;
  const read = readKeys(graph, before.id);
  const fresh = only(
    next.filter(
      (other) =>
        !stored.has(wireOf(other)) &&
        typeof other.key === "string" &&
        other.key !== "" &&
        !read.has(other.key),
    ),
  );
  const from = only(orphans());
  return fresh === null || from === null ? null : { from, to: fresh.key as string };
}

function carriedSource(
  source: BindingSource,
  mergeId: Uuid,
  rename: MergeKeyRename,
): BindingSource {
  const moved = (ref: NodeOutputRef) =>
    ref.node_id === mergeId &&
    ref.field_path[0] === "branches" &&
    ref.field_path[1] === rename.from;
  const carry = (ref: NodeOutputRef): NodeOutputRef =>
    moved(ref)
      ? { ...ref, field_path: [ref.field_path[0] as string, rename.to, ...ref.field_path.slice(2)] }
      : ref;
  if (source.kind === "node_output") return carry(source);
  if (
    source.kind === "template" &&
    source.parts.some((part) => typeof part !== "string" && moved(part))
  ) {
    return {
      ...source,
      parts: source.parts.map((part) => (typeof part === "string" ? part : carry(part))),
    };
  }
  return source;
}

/** `graph` with everything that read `branches.<from>` of the merge reading `branches.<to>`. */
export function carryMergeKeyRename(
  graph: WorkflowGraph,
  mergeId: Uuid,
  rename: MergeKeyRename,
): WorkflowGraph {
  return {
    ...graph,
    bindings: graph.bindings.map((binding) => {
      const source = carriedSource(binding.source, mergeId, rename);
      return source === binding.source ? binding : { ...binding, source };
    }),
  };
}
