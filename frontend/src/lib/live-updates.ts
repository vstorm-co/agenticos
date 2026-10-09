import type { QueryKey } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import type { ChangeEvent, ChangeResource } from "@/types/change-events";

/**
 * Which cached answers a change makes stale. Whole families rather than the one
 * row: a renamed agent is also a different row in every list that shows it, and
 * a member removed from the organization is also gone from each group.
 */
const STALE: Record<ChangeResource, (orgId: string) => QueryKey[]> = {
  agent: () => [qk.agents.all()],
  skill: () => [qk.skills.all()],
  context: () => [qk.context.all()],
  knowledge_base: () => [qk.kb.all()],
  artifact: () => [qk.artifacts.all()],
  member: (orgId) => [
    qk.organizations.members(orgId),
    qk.organizations.groups(orgId),
    // A role changed may be the reader's own.
    qk.organizations.permissions(orgId),
  ],
  invitation: (orgId) => [qk.invitations.list(orgId)],
  group: (orgId) => [qk.organizations.groups(orgId)],
  organization: () => [qk.organizations.all()],
};

export function staleQueries(event: ChangeEvent): QueryKey[] {
  return STALE[event.resource](event.organization_id);
}

type Listener = (event: ChangeEvent) => void;

const listeners = new Set<Listener>();

/** Hear every change the console's socket delivers. Returns the unsubscribe. */
export function onRemoteChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function announceChange(event: ChangeEvent): void {
  for (const listener of listeners) listener(event);
}
