"use client";

import { type WorkflowApp, appForCatalogKey } from "@/components/workflows/apps";
import { usePermissions, useUsableMcpConnections } from "@/hooks";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { Perm } from "@/types/permissions";

/**
 * The organization's MCP connections as the picker, the cards and the step panel
 * read them, through the cache `useMcpToolSchema` shares.
 *
 * Read by anybody who may edit the open workflow. `connections` is `null` while loading and
 * for a member who may not edit it - "not known", never "none" - and `unavailable`
 * says which of the two it is. Only a member who manages connections can add one.
 */
export function useAppConnections(): {
  connections: UsableMcpConnectionRecord[] | null;
  canConnect: boolean;
  unavailable: boolean;
} {
  const { can } = usePermissions();
  const { connections, canRead } = useUsableMcpConnections();
  return { connections, canConnect: can(Perm.mcpManage), unavailable: !canRead };
}

/** An `mcp.call` step whose connection belongs to an app the picker groups by. */
export interface McpAppStep {
  app: WorkflowApp;
  connection: UsableMcpConnectionRecord;
  tool: string;
}

/** The app an `mcp.call` step's connection maps to, or null for any other step or a connection unknown here. */
export function useMcpAppStep(config: Record<string, unknown>): McpAppStep | null {
  const { connections } = useAppConnections();
  const connection = connections?.find((one) => one.id === config.connection_id);
  const tool = typeof config.tool === "string" ? config.tool : "";
  const app = connection === undefined ? null : appForCatalogKey(connection.catalog_key, tool);
  if (connection === undefined || app === null) return null;
  return { app, connection, tool };
}
