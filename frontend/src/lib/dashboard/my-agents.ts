/**
 * The my-agents card's three inner permission checks, as pure functions.
 *
 * The card renders differently per caller: without `agents:edit` it shows
 * only what was shared (a viewer has no "yours"), run counts appear only
 * under `runs:view`, and the "Open chat" button only under `agents:run` - a
 * control the caller may not use is not rendered. Injected `can`, same rule
 * as the registry's gates, so the matrix is testable without a component.
 */

import { Perm, type Permission } from "@/types/permissions";

export interface MyAgentsPolicy {
  /** Without agents:edit the caller has no "yours" - only what was shared. */
  includeOwn: boolean;
  showRunCounts: boolean;
  showOpenChat: boolean;
}

export function myAgentsPolicy(can: (permission: Permission) => boolean): MyAgentsPolicy {
  return {
    includeOwn: can(Perm.agentsEdit),
    showRunCounts: can(Perm.runsView),
    showOpenChat: can(Perm.agentsRun),
  };
}

export function agentTag(
  row: { owner_user_id: string | null },
  userId: string | null,
): "yours" | "shared" {
  return userId !== null && row.owner_user_id === userId ? "yours" : "shared";
}

export function filterAgentRows<T extends { owner_user_id: string | null }>(
  rows: T[],
  policy: MyAgentsPolicy,
  userId: string | null,
): T[] {
  if (policy.includeOwn) return rows;
  return rows.filter((row) => agentTag(row, userId) === "shared");
}
