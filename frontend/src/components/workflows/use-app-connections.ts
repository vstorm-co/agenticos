"use client";

import {
  type WorkflowApp,
  appForCatalogKey,
  catalogWorkflowApp,
  connectionWorkflowApp,
  LOGIN_TOOLS,
} from "@/components/workflows/apps";
import { usePermissions, useUsableMcpConnections } from "@/hooks";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { useMcpCatalog, useMcpCatalogPage } from "@/hooks/use-mcp-servers";
import type { McpCatalogEntry } from "@/types/mcp";
import { useDebounced } from "@/components/ui/list-controls";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { testOrgMcpConnection } from "@/lib/org-mcp-connections-api";
import { qk } from "@/lib/query-keys";
import { Perm } from "@/types/permissions";

/**
 * The organization's MCP connections as the picker, the cards and the step panel
 * read them, through the cache `useMcpToolSchema` shares.
 *
 * Read by anybody who may edit the open workflow. `connections` is `null` while loading and
 * for a member who may not edit it - "not known", never "none" - and `unavailable`
 * says which of the two it is. Only a member who manages connections can add one.
 */
export function useAppConnections(search?: string): {
  connections: UsableMcpConnectionRecord[] | null;
  servers: McpCatalogEntry[];
  canConnect: boolean;
  unavailable: boolean;
} {
  const { can } = usePermissions();
  const { connections, canRead } = useUsableMcpConnections();
  const { servers: curated } = useMcpCatalog();
  const settled = useDebounced(search ?? "");
  const registry = useMcpCatalogPage(
    settled,
    "",
    "",
    0,
    search !== undefined && settled.trim() !== "",
  );
  const servers = [
    ...new Map(
      [...curated, ...(search === undefined ? [] : registry.servers)].map((entry) => [
        entry.key,
        entry,
      ]),
    ).values(),
  ];
  return { connections, servers, canConnect: can(Perm.mcpManage), unavailable: !canRead };
}

/** An `mcp.call` step whose connection belongs to an app the picker groups by. */
export interface McpAppStep {
  app: WorkflowApp;
  connection: UsableMcpConnectionRecord;
  tool: string;
}

/** The app an `mcp.call` step's connection maps to, or null for any other step or a connection unknown here. */
export function useMcpAppStep(config: Record<string, unknown>): McpAppStep | null {
  const { connections, servers } = useAppConnections();
  const connection = connections?.find((one) => one.id === config.connection_id);
  const tool = typeof config.tool === "string" ? config.tool : "";
  if (LOGIN_TOOLS.has(tool)) return null;
  const entry = servers.find((server) => server.key === connection?.catalog_key);
  const app =
    connection === undefined
      ? null
      : (appForCatalogKey(connection.catalog_key, tool) ??
        (entry === undefined ? connectionWorkflowApp(connection) : catalogWorkflowApp(entry)));
  if (connection === undefined || app === null) return null;
  return { app, connection, tool };
}

/** Probe a connected server and refresh the same tool inventory the picker reads. */
export function useRefreshWorkflowMcpTools() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await testOrgMcpConnection(id);
      await client.invalidateQueries({ queryKey: qk.mcpConnections.all() });
      if (result.error) throw new Error(result.error);
      return result;
    },
  });
}
