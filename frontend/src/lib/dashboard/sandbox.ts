/**
 * What the sandbox cards decide before they render anything.
 *
 * Out of the React for the reason the rest of `lib/dashboard` is: a decision
 * taken inside a component is a decision only a mounted query client can test.
 * Two of the ones here encode a limit of today's API rather than a preference,
 * and both are load-bearing.
 *
 * **There is no client-side count for the host's own ceilings.**
 * `GET /sandbox-connections/{id}/sessions` filters its rows to the caller's
 * organization and passes `limit` and `open_limit` through from the daemon
 * untouched, so those two are ceilings for *every* tenant on the host while
 * `sessions.length` counts one. `sessions.length / limit` is a fraction whose
 * halves disagree, and a wrong number is worse than no number - which is why
 * {@link tenantShare} divides by `tenant_limit` and by nothing else, and why the
 * host's ceilings are rendered as ceilings.
 *
 * **Whether a connection holds sessions at all is a fact about the row, not
 * about the answer.** A Daytona connection answers with an empty list, which is
 * the same shape an idle Docker host answers with, and the `kind` the service
 * puts beside it is dropped by the response model. So {@link holdsSessions} asks
 * the connection record, which carries `kind` already.
 */

import { formatBytes } from "@/lib/utils";
import type {
  SandboxConnectionRecord,
  SandboxSession,
  SandboxSessionList,
} from "@/lib/sandbox-connections-api";

/** The connections worth asking about: the ones an agent can still reach. */
export function watchableConnections(
  connections: SandboxConnectionRecord[],
): SandboxConnectionRecord[] {
  return connections.filter((connection) => connection.is_active);
}

/**
 * The one connection the per-session cards read.
 *
 * The default, because that is the host an agent naming none resolves to, and
 * the capacity card is the one that covers every connection. Falls back to the
 * first active one so a deployment that registered a host without promoting it
 * is not shown an empty card about a host that is running things.
 */
export function primaryConnection(
  connections: SandboxConnectionRecord[],
): SandboxConnectionRecord | null {
  const watchable = watchableConnections(connections);
  return watchable.find((connection) => connection.is_default) ?? watchable[0] ?? null;
}

/** Whether sandboxes of ours run here at all - see the note on this module. */
export function holdsSessions(connection: SandboxConnectionRecord): boolean {
  return connection.kind === "docker";
}

export interface TenantShare {
  /** This organization's open sandboxes. Every row in the listing is ours. */
  used: number;
  /** The ceiling that applies to this organization, or null if it sets none. */
  limit: number | null;
  /** `used` against `limit` as a percentage, or null when there is no ceiling. */
  percent: number | null;
}

/**
 * The only honest fraction this API supports: ours against our own ceiling.
 *
 * This is the number that answers "why did an agent just get a 429" - the host
 * refuses a session because the organization is at `max_sessions_per_tenant`,
 * and nothing else on the page says so.
 */
export function tenantShare(listing: SandboxSessionList): TenantShare {
  const used = listing.sessions.length;
  const limit = listing.tenant_limit;
  const bounded = limit !== null && limit > 0;
  return {
    used,
    limit,
    percent: bounded ? Math.min(Math.round((used / limit) * 100), 100) : null,
  };
}

const SCOPE_KEYS: Record<string, string> = {
  agent: "scope.agent",
  conversation: "scope.conversation",
  channel: "scope.channel",
  user: "scope.user",
};

/**
 * An i18n key for what shares one sandbox, never the sentence itself.
 *
 * `null` is a `run`-scoped sandbox rather than an attribution that went missing:
 * it has no `agent_workspaces` row by design, so there was never a row to join.
 * A scope this vocabulary does not know is reported as unknown rather than
 * folded into the widest one - who can read a sandbox's files is exactly what
 * the scope says, and guessing it wrong describes the wrong set of people.
 */
export function scopeKey(scope: string | null): string {
  if (scope === null) return "scope.run";
  return SCOPE_KEYS[scope] ?? "scope.unknown";
}

/** Seconds since a sandbox last did anything, as a message key and a number. */
export function idleLabel(seconds: number): { key: string; count: number } {
  if (seconds < 60) return { key: "idle.seconds", count: Math.round(seconds) };
  if (seconds < 3600) return { key: "idle.minutes", count: Math.round(seconds / 60) };
  return { key: "idle.hours", count: Math.round(seconds / 3600) };
}

/**
 * Memory against the ceiling of that sandbox alone, already formatted.
 *
 * Null when the sample was never taken, which is the normal case: sampling costs
 * the service a daemon round trip per sandbox, so it is asked for by hand.
 */
export function memoryLabel(
  session: SandboxSession,
): { used: string; limit: string | null } | null {
  const used = session.usage?.memory_bytes;
  if (used === null || used === undefined) return null;
  const limit = session.usage?.memory_limit_bytes;
  return { used: formatBytes(used), limit: limit ? formatBytes(limit) : null };
}
