/**
 * Which connections need a person's attention, counted for the sidebar badge
 * and the Connections tabs.
 *
 * The definitions are the ones the Connections page already renders, so the
 * badge cannot disagree with the page it points at:
 *
 * - an MCP connection (personal or organization) is in trouble when
 *   `connectionState` says so - `needs-authorization` or `error` - the same
 *   worst-state rule the MCP list's row status reads;
 * - a managed app account is in trouble when the Apps tab would offer
 *   Reconnect for it: enabled, but not usable.
 *
 * A disabled connection is intentional, never trouble. An app account is the
 * same row as a personal MCP connection - `AppConnectionRead.id` is the
 * `McpConnection` id - so the total counts distinct ids, not lists, and one
 * expired app never counts twice.
 */

import { appConnectionUsable } from "@/lib/app-connection-journey";
import { connectionState } from "@/lib/mcp-servers";
import type { AppConnection } from "@/types/app-connections";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

/**
 * Whether this MCP connection needs attention: its credential cannot be used
 * (`needs-authorization`, an expired or revoked grant or a token the deployment
 * can no longer unseal) or its last probe failed (`error`).
 */
export function mcpConnectionNeedsAttention(
  connection: Pick<McpConnectionRecord, "authorized" | "is_enabled" | "last_status">,
): boolean {
  const state = connectionState(connection);
  return state === "needs-authorization" || state === "error";
}

/** Whether this managed app account needs attention: enabled, but not usable. */
export function appConnectionNeedsAttention(connection: AppConnection): boolean {
  return connection.is_enabled && !appConnectionUsable(connection);
}

/** How many connections need attention, per surface and in total. */
export interface ConnectionHealthCounts {
  /** Managed app accounts the Apps tab would offer Reconnect for. */
  apps: number;
  /** MCP connections - personal and organization - in a trouble state. */
  mcp: number;
  /** Distinct connections in trouble across every list. */
  total: number;
}

export function connectionHealthCounts(
  personal: readonly McpConnectionRecord[],
  organization: readonly OrgMcpConnectionRecord[],
  apps: readonly AppConnection[],
): ConnectionHealthCounts {
  const mcpTroubled = new Set<string>();
  for (const connection of personal) {
    if (mcpConnectionNeedsAttention(connection)) mcpTroubled.add(connection.id);
  }
  for (const connection of organization) {
    if (mcpConnectionNeedsAttention(connection)) mcpTroubled.add(connection.id);
  }
  // The total is the union, not the sum: an app account is the same row as a
  // personal MCP connection, so one expired app is one broken connection.
  const troubled = new Set(mcpTroubled);
  let appsCount = 0;
  for (const connection of apps) {
    if (appConnectionNeedsAttention(connection)) {
      appsCount += 1;
      troubled.add(connection.id);
    }
  }
  return { apps: appsCount, mcp: mcpTroubled.size, total: troubled.size };
}
