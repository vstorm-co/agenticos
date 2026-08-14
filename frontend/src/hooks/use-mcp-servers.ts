"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { McpToolInfo } from "@/lib/mcp-connections-api";
import { mergeServers, type McpServerRow } from "@/lib/mcp-servers";
import { qk } from "@/lib/query-keys";
import type { McpCatalog } from "@/types/mcp";
import { useMcpConnections } from "./use-mcp-connections";
import { useOrgMcpConnections } from "./use-org-mcp-connections";

/**
 * The organization's MCP catalog.
 *
 * Cached indefinitely: the list is hand-curated in the backend and changes when
 * it is redeployed, not while someone is reading it.
 */
export function useMcpCatalog() {
  const { data, isLoading } = useQuery({
    queryKey: qk.mcpServers.catalog(),
    queryFn: () => apiClient.get<McpCatalog>("/agents/mcp-catalog"),
    staleTime: Infinity,
  });
  return { servers: data?.items ?? [], isLoading };
}

export type { McpServerRow };

/**
 * Every MCP server, with who has connected it and what it offers.
 *
 * One hook for what used to be two pages. The catalog says which servers exist;
 * the two connection lists say who holds a credential to each. Presenting those
 * as separate screens is what made the difference between them unanswerable, so
 * they are joined here and the page renders rows.
 *
 * Probe results are held in local state rather than the query cache because
 * they are not a resource anyone can GET - they exist only as the answer to a
 * check somebody asked for. The lists, which a check does change server-side,
 * are refetched by the hook that owns them.
 */
export function useMcpServers() {
  const catalog = useQuery({
    queryKey: qk.mcpServers.catalog(),
    queryFn: () => apiClient.get<McpCatalog>("/agents/mcp-catalog"),
    staleTime: Infinity,
  });
  const organization = useOrgMcpConnections();
  const personal = useMcpConnections();

  const [toolsByConnection, setToolsByConnection] = useState<Record<string, McpToolInfo[]>>({});

  const rows = useMemo(
    () => mergeServers(catalog.data?.items ?? [], organization.connections, personal.connections),
    [catalog.data, organization.connections, personal.connections],
  );

  return {
    rows,
    isLoading: catalog.isLoading || organization.isLoading || personal.isLoading,
    /**
     * A failure everybody's view depends on is reported — the catalog and the
     * caller's own connections. The organization list's is not: a member
     * without `connections:manage` gets a 403 there and can still read the
     * other two, so surfacing it as the page's error would replace a usable
     * screen with a refusal about one column of it. A failed catalog is the
     * opposite case — without it `mergeServers` yields an empty page dressed
     * as "no servers", on the one deployment state that cannot be true.
     */
    error: catalog.error ?? personal.error,
    organization,
    personal,
    /** Tools discovered by a check in this session, keyed by connection id. */
    toolsByConnection,
    recordTools: (connectionId: string, tools: McpToolInfo[]) =>
      setToolsByConnection((previous) => ({ ...previous, [connectionId]: tools })),
  };
}
