import type { WorkflowGraph } from "@/lib/workflows/types";

/**
 * One client-side validation problem, field-scoped the same way the server's
 * `GraphValidationError` is — so the property panel can show a per-field message
 * and the footer can collect them into a problems list.
 */
export interface ValidationProblem {
  /** The offending node, or null for a graph-level rule. */
  nodeId: string | null;
  /** The offending field (a `Binding.target_field` path), or null. */
  field: string | null;
  /** A stable code mirroring the server rule, for grouping and links. */
  code: string;
  /** Already-translated, human-readable text. */
  message: string;
}

/**
 * The client-side mirror of #1786's eight validation rules (exactly-one-input,
 * reachable-outputs, type-compatibility, branch-local data availability,
 * exclusive-merge, nested-scope boundaries, no cycles, no parallel fan-out).
 *
 * Deliberately non-authoritative: publish always re-validates server-side, and
 * drift degrades to a worse editing experience, never a correctness bug.
 *
 * TODO(#1787 validation leaf): implement the eight-rule mirror and the
 * fixture-graph drift test (both implementations, same inputs). The foundation
 * reports no problems so the editor never blocks on a rule not yet ported.
 */
export function validateGraph(_graph: WorkflowGraph): ValidationProblem[] {
  return [];
}
