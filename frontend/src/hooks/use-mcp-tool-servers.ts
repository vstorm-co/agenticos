"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { listMcpConnections } from "@/lib/mcp-connections-api";
import { listOrgMcpConnections } from "@/lib/org-mcp-connections-api";
import type { McpServerRef } from "@/lib/tool-steps";

/**
 * The MCP servers this caller could be talking to, for naming their tool calls.
 *
 * A tool call reaches the transcript as a name and some arguments - nothing on it says
 * it came from an MCP server. What identifies one is the prefix the backend puts on
 * every tool it exposes, which is the connection's name, so matching a call against
 * the connections this caller has is the only way to turn `linear_create_issue` into
 * *Linear · Create issue*.
 *
 * Both scopes, because an agent's spec can name either: the organization's servers and
 * the member's own. Read-only and cached under the same keys the settings screens use,
 * so a chat that never sees an MCP call costs one list request and a chat that sees a
 * hundred costs the same one.
 *
 * A miss is not a failure. An agent whose server has since been deleted, or a member
 * who cannot list the connection, gets the humanised tool name - which is what the
 * step showed before any of this.
 */
export function useMcpToolServers(): McpServerRef[] {
  const { data: personal = [] } = useQuery({
    queryKey: qk.mcpConnections.list(),
    queryFn: listMcpConnections,
    staleTime: 5 * 60 * 1000,
  });
  const { data: organization = [] } = useQuery({
    queryKey: qk.mcpConnections.org(),
    queryFn: listOrgMcpConnections,
    staleTime: 5 * 60 * 1000,
  });

  return useMemo(
    () => [
      ...organization.map(({ name, url }) => ({ name, url })),
      ...personal.map(({ name, url }) => ({ name, url })),
    ],
    [organization, personal],
  );
}
