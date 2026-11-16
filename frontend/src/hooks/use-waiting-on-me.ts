"use client";

import { usePermissions } from "@/hooks/use-permissions";
import { useSuggestions } from "@/hooks/use-suggestions";
import { Perm } from "@/types/permissions";

export type WaitingKind = "approvals" | "suggestions";

/** Personal decisions only: tool approvals and the reader's open Inbox proposals. */
export function waitingOn(
  approvals: number,
  others: { suggestions: number },
): [WaitingKind, number][] {
  return (
    [
      ["approvals", approvals],
      ["suggestions", others.suggestions],
    ] satisfies [WaitingKind, number][]
  ).filter(([, count]) => count > 0);
}

/** Shares the Briefing query; authoring queues and evaluation health belong to other views. */
export function useWaitingOnMe() {
  const { can, isLoaded } = usePermissions();
  const enabled = can(Perm.agentsRun);
  const proposals = useSuggestions(enabled);
  return {
    suggestions: enabled ? proposals.suggestions.length : 0,
    settled: isLoaded && (!enabled || (!proposals.isLoading && proposals.error === null)),
    failed: enabled && proposals.error !== null,
    retry: () => {
      if (enabled && proposals.error !== null) void proposals.refetch();
    },
  };
}
