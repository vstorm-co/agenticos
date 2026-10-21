import type { QueryKey } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import type { ChangeEvent, ChangeResource } from "@/types/change-events";

/**
 * Which cached answers a change makes stale. Whole families rather than the one
 * row: a renamed agent is also a different row in every list that shows it, and
 * a member removed from the organization is also gone from each group. A row
 * shareable with people also refreshes the sharing panels - a grant made in one
 * tab is the audience another tab is showing.
 */
const STALE: Record<ChangeResource, (orgId: string) => QueryKey[]> = {
  // The Architect's bubble says whether there is an agent yet.
  agent: (orgId) => [qk.agents.all(), qk.sharing.all(), qk.runs.assistantSignals(orgId)],
  skill: () => [qk.skills.all(), qk.sharing.all()],
  context: () => [qk.context.all(), qk.sharing.all()],
  knowledge_base: () => [qk.kb.all(), qk.sharing.all()],
  artifact: () => [qk.artifacts.all(), qk.sharing.all()],
  member: (orgId) => [
    qk.organizations.members(orgId),
    qk.organizations.groups(orgId),
    // A role changed may be the reader's own.
    qk.organizations.permissions(orgId),
  ],
  invitation: (orgId) => [qk.invitations.list(orgId)],
  // A group's members and shares are who reaches what it was shared.
  group: (orgId) => [qk.organizations.groups(orgId), qk.sharing.all()],
  // The organization's settings, the AI Architect's among them.
  organization: (orgId) => [qk.organizations.all(), qk.assistant(orgId)],
  trigger: () => [qk.triggers.all()],
  // A bot is also the surface an agent is exposed on.
  channel: () => [qk.channelBots.list(), qk.exposures.all()],
  notification: () => [qk.notifications.all()],
  secret: () => [qk.secrets.all(), qk.sharing.all()],
  mcp_connection: () => [qk.mcpConnections.all(), qk.sharing.all()],
  // Run history, the approvals inbox and spend all live under `runs`; the chat
  // list reads its running, unread and order state off runs too - a run started
  // by the API, a routine or another tab would otherwise leave it stale. The
  // lists only: refetching an open thread's messages under a stream is not this.
  run: () => [qk.runs.all(), qk.conversations.list()],
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
