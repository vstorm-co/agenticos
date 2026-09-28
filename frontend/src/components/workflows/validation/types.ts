/**
 * Shared types for the client-side validation mirror.
 *
 * A rule produces a {@link RawProblem} — a code plus the node / edge / field it
 * scopes to, and any interpolation values its message needs — and stays pure: it
 * never translates. `validateGraph` turns each raw problem into a
 * {@link ValidationProblem} by resolving its code to a `next-intl` key and calling
 * the caller's translator once. Keeping translation out of the rules is what lets
 * every rule and every exported helper be unit-tested without a translator in hand.
 */

/**
 * A stable code for one violated rule, mirroring the server's `validate.py`.
 *
 * The property panel groups and links problems by this, and the drift fixtures
 * assert on it rather than on translated text — the mirror is fixture-parity with
 * the backend, so the code is the contract, not the sentence.
 */
export type ValidationCode =
  // Dangling references — an edge or binding naming a node not in the graph.
  | "edge-source-node-missing"
  | "edge-target-node-missing"
  | "binding-target-node-missing"
  | "binding-source-node-missing"
  // Resource resolution the client can mirror (no deployment scopes, no database).
  | "unknown-definition"
  // Rule 1 — exactly one input.
  | "entry-not-in-graph"
  | "entry-is-edge-target"
  // Rule 2 — reachable outputs.
  | "unreachable-node"
  // Rule 3 — type compatibility.
  | "edge-source-port-unknown"
  | "edge-target-port-unknown"
  | "edge-incompatible"
  | "binding-field-path-unknown"
  | "binding-incompatible"
  // Rule 4 — branch-local data availability.
  | "binding-self-reference"
  | "binding-unavailable"
  // Rule 5 — exclusive merge.
  | "merge-duplicate-branch"
  | "merge-no-common-dominator"
  | "merge-not-from-if"
  | "merge-not-exclusive"
  // Rule 6 — nested scope boundaries.
  | "edge-crosses-scope"
  | "binding-crosses-scope"
  // Rule 7 — no cycles.
  | "node-in-cycle"
  | "node-in-scope-cycle"
  // Rule 8 — no parallel fan-out.
  | "fanout-multiple-ports"
  | "fanout-port-multiple-edges"
  // Rule 9 — every required input bound exactly once.
  | "input-bound-twice"
  | "input-not-bound";

/**
 * The `next-intl` key each code renders through, under the top-level `workflows`
 * namespace. Kept as plain string literals so the i18n guard's "a key nothing
 * reads" sweep counts every one as read (it matches a namespace-relative spelling
 * appearing as a literal in source); the English text lives only in `en.json`.
 */
export const MESSAGE_KEYS: Record<ValidationCode, string> = {
  "edge-source-node-missing": "validationEdgeSourceNodeMissing",
  "edge-target-node-missing": "validationEdgeTargetNodeMissing",
  "binding-target-node-missing": "validationBindingTargetNodeMissing",
  "binding-source-node-missing": "validationBindingSourceNodeMissing",
  "unknown-definition": "validationUnknownDefinition",
  "entry-not-in-graph": "validationEntryNotInGraph",
  "entry-is-edge-target": "validationEntryIsEdgeTarget",
  "unreachable-node": "validationUnreachableNode",
  "edge-source-port-unknown": "validationEdgeSourcePortUnknown",
  "edge-target-port-unknown": "validationEdgeTargetPortUnknown",
  "edge-incompatible": "validationEdgeIncompatible",
  "binding-field-path-unknown": "validationBindingFieldPathUnknown",
  "binding-incompatible": "validationBindingIncompatible",
  "binding-self-reference": "validationBindingSelfReference",
  "binding-unavailable": "validationBindingUnavailable",
  "merge-duplicate-branch": "validationMergeDuplicateBranch",
  "merge-no-common-dominator": "validationMergeNoCommonDominator",
  "merge-not-from-if": "validationMergeNotFromIf",
  "merge-not-exclusive": "validationMergeNotExclusive",
  "edge-crosses-scope": "validationEdgeCrossesScope",
  "binding-crosses-scope": "validationBindingCrossesScope",
  "node-in-cycle": "validationNodeInCycle",
  "node-in-scope-cycle": "validationNodeInScopeCycle",
  "fanout-multiple-ports": "validationFanoutMultiplePorts",
  "fanout-port-multiple-edges": "validationFanoutPortMultipleEdges",
  "input-bound-twice": "validationInputBoundTwice",
  "input-not-bound": "validationInputNotBound",
};

/** Interpolation values for a message, passed straight to the translator. */
export type MessageValues = Record<string, string | number>;

/** A rule's finding before translation: a code, what it scopes to, and its values. */
export interface RawProblem {
  /** The offending node, or null for a graph-level or edge-scoped problem. */
  nodeId: string | null;
  /** The offending edge, or null. */
  edgeId: string | null;
  /** The offending field (a `Binding.target_field` path), or null. */
  field: string | null;
  /** The stable rule code. */
  code: ValidationCode;
  /** Interpolation values the message needs, if any. */
  params?: MessageValues;
}

/**
 * A translator for the top-level `workflows` namespace — structurally what
 * `useTranslations("workflows")` returns, narrowed to the calls this module makes.
 * A caller passes the real `next-intl` translator; a test passes any stub.
 */
export type ValidationTranslator = (key: string, values?: MessageValues) => string;
