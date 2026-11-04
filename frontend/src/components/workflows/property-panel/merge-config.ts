import { carryMergeKeyRename } from "@/lib/workflows/merge-key-rename";
import type { PortRename } from "@/lib/workflows/port-rename";
import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { analyse, anyPairRunsTogether } from "@/components/workflows/validation/joins";
import { branchKeys, rule7NoCycles } from "@/components/workflows/validation/rules";
import {
  deriveScopes,
  nodeScopeMap,
  type DefinitionMap,
} from "@/components/workflows/validation/topology";

const MERGE = "logic.merge";
const KEY_LIMIT = 32;

/** The wire a stored branch key names, in the form `branchKeys` reads it. */
function wireId(sourceNodeId: string, sourcePort: string): string {
  return `${sourceNodeId}\u0000${sourcePort}`;
}

/** The `branch_keys` entries of a merge's config that are well formed, by wire. */
function storedKeys(config: Record<string, unknown>): Map<string, string> {
  const stored = new Map<string, string>();
  const entries = config.branch_keys;
  for (const item of Array.isArray(entries) ? entries : []) {
    if (typeof item !== "object" || item === null) continue;
    const { source_node_id: source, source_port: port, key } = item as Record<string, unknown>;
    if (typeof source === "string" && typeof port === "string" && typeof key === "string") {
      stored.set(wireId(source, port), key);
    }
  }
  return stored;
}

/** `key` made different from every name in `taken` with `_2`, `_3`, ... within the key length. */
function uniquified(key: string, taken: ReadonlySet<string>): string {
  const base = key === "" ? "branch" : key;
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const suffix = `_${n}`;
    const candidate = `${base.slice(0, KEY_LIMIT - suffix.length)}${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/**
 * The branches reaching a merge with the name each goes by, in wire order: the key the
 * config stores for a wire that is still there, else the default (the Split's branch
 * name, or a slug of the step's name) made unique among the others. A stored key that
 * names a wire which is gone - a pasted merge's, or one whose leg was removed - is not
 * a branch and is dropped.
 */
export function mergeBranches(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
  merge: NodeInstance,
): { source_node_id: string; source_port: string; key: string }[] {
  const stored = storedKeys(merge.config);
  const defaults = branchKeys(graph, definitions, {
    ...merge,
    config: { ...merge.config, branch_keys: [] },
  });
  const wires = [...defaults.keys()];
  const taken = new Set(wires.flatMap((wire) => stored.get(wire) ?? []));
  return wires.map((wire) => {
    const [source_node_id, source_port] = wire.split("\u0000") as [string, string];
    const key = stored.get(wire) ?? uniquified(defaults.get(wire) as string, taken);
    taken.add(key);
    return { source_node_id, source_port, key };
  });
}

/**
 * The config `mergeId` should have in `graph` for how its branches reach it, or `null`
 * when what it has already fits.
 *
 * The mode is picked from the graph - branches that can run together need "all
 * branches", branches of which only one runs need "the branch that ran" - but only when
 * the stored mode would be refused, so an author's explicit choice is kept; a merge
 * with one branch is left as it is. Under "all branches" every branch has a name:
 * the stored one, or a default made unique.
 */
export function fittingMergeConfig(
  graph: WorkflowGraph,
  mergeId: string,
  definitions: DefinitionMap,
): Record<string, unknown> | null {
  const merge = graph.nodes.find((n) => n.id === mergeId);
  if (merge === undefined || definitions.get(mergeId)?.id !== MERGE) return null;
  const nodeScope = nodeScopeMap(deriveScopes(graph, definitions));
  const analysis = analyse(
    graph,
    definitions,
    nodeScope,
    rule7NoCycles(graph, nodeScope).order !== null,
  );
  if ((analysis.incoming.get(mergeId) ?? []).length < 2) return null;

  const stored = merge.config.wait_for === "all" ? "all" : "one";
  const needed = anyPairRunsTogether(analysis, mergeId) ? "all" : "one";
  if (stored === needed && stored === "one") return null;
  const next: Record<string, unknown> = { ...merge.config };
  if (stored !== needed) next.wait_for = needed;
  if (needed === "all") next.branch_keys = mergeBranches(graph, definitions, merge);
  return JSON.stringify(next) === JSON.stringify(merge.config) ? null : next;
}

/** {@link fittingMergeConfig} for each of `mergeIds` that is a merge needing a change, by id. */
export function fittingMergeConfigs(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
  mergeIds: readonly string[],
): Record<string, Record<string, unknown>> {
  const configs: Record<string, Record<string, unknown>> = {};
  for (const id of mergeIds) {
    const config = fittingMergeConfig(graph, id, definitions);
    if (config !== null) configs[id] = config;
  }
  return configs;
}

/**
 * `config` with the name stored for the branch leaving `from` stored for the one leaving
 * `to` instead - a step put into that branch's wire is that branch now. Unchanged when
 * `from` has no stored name.
 */
export function carryBranchKey(
  config: Record<string, unknown>,
  from: { nodeId: string; port: string },
  to: { nodeId: string; port: string },
): Record<string, unknown> {
  const entries = config.branch_keys;
  if (!Array.isArray(entries)) return config;
  return {
    ...config,
    branch_keys: entries.map((entry) =>
      typeof entry === "object" &&
      entry !== null &&
      wireId(String(entry.source_node_id), String(entry.source_port)) ===
        wireId(from.nodeId, from.port)
        ? { ...entry, source_node_id: to.nodeId, source_port: to.port }
        : entry,
    ),
  };
}

/**
 * Whether a merge the renamed port feeds, with no key stored for that wire, goes on
 * naming the branch by its port: the key defaults to the port name, so what reads
 * `branches.<old>` follows the rename and nothing is stored. Refused when another
 * wire of the merge or a stored key already goes by either name, since the default
 * may then have been made unique.
 */
function carriesUnstoredKey(
  graph: WorkflowGraph,
  mergeId: string,
  entries: ReadonlyMap<string, string>,
  to: { nodeId: string; port: string },
  rename: PortRename,
): boolean {
  const names = new Set([rename.from, rename.to]);
  const incoming = graph.edges.filter((edge) => edge.target_node_id === mergeId);
  const feeds = incoming.some(
    (edge) => edge.source_node_id === to.nodeId && edge.source_port === to.port,
  );
  if (!feeds || entries.has(wireId(to.nodeId, to.port))) return false;
  const clash = incoming.some(
    (edge) =>
      !(edge.source_node_id === to.nodeId && edge.source_port === to.port) &&
      names.has(edge.source_port),
  );
  return !clash && ![...entries.values()].some((key) => names.has(key));
}

/**
 * `graph` with every merge the renamed step feeds still naming that branch: the stored
 * wire follows the port. A key stored under the old port name is the default and
 * follows it too - together with what reads `branches.<key>` - unless another branch
 * already goes by the new name; any other key is the author's and stays as it is.
 */
export function carryPortRenameToMerges(
  graph: WorkflowGraph,
  nodeId: string,
  rename: PortRename,
): WorkflowGraph {
  const from = { nodeId, port: rename.from };
  const to = { nodeId, port: rename.to };
  let carried = graph;
  const nodes = graph.nodes.map((node) => {
    if (node.definition_id !== MERGE) return node;
    const entries = storedKeys(node.config);
    if (!entries.has(wireId(from.nodeId, from.port))) {
      if (carriesUnstoredKey(graph, node.id, entries, to, rename)) {
        carried = carryMergeKeyRename(carried, node.id, { from: rename.from, to: rename.to });
      }
      return node;
    }
    let config = carryBranchKey(node.config, from, to);
    if (
      entries.get(wireId(from.nodeId, from.port)) === rename.from &&
      ![...entries.values()].includes(rename.to)
    ) {
      config = {
        ...config,
        branch_keys: (config.branch_keys as Record<string, unknown>[]).map((entry) =>
          wireId(String(entry.source_node_id), String(entry.source_port)) ===
          wireId(to.nodeId, to.port)
            ? { ...entry, key: rename.to }
            : entry,
        ),
      };
      carried = carryMergeKeyRename(carried, node.id, { from: rename.from, to: rename.to });
    }
    return { ...node, config };
  });
  return { ...carried, nodes };
}
