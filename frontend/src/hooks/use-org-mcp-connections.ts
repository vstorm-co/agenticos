"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  createOrgMcpConnection,
  deleteOrgMcpConnection,
  listOrgMcpConnections,
  listOrgMcpToolCalls,
  testOrgMcpConnection,
  updateOrgMcpConnection,
  type OrgMcpConnectionInput,
  type OrgMcpConnectionPatch,
  type OrgMcpConnectionRecord,
} from "@/lib/org-mcp-connections-api";
import type { McpConnectionTestResult } from "@/lib/mcp-connections-api";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";

interface UseOrgMcpConnectionsResult {
  connections: OrgMcpConnectionRecord[];
  isLoading: boolean;
  /** True for a background refresh of a cached list as well as a first load. */
  isFetching: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (input: OrgMcpConnectionInput) => Promise<OrgMcpConnectionRecord>;
  update: (id: string, patch: OrgMcpConnectionPatch) => Promise<OrgMcpConnectionRecord>;
  remove: (id: string) => Promise<void>;
  test: (id: string) => Promise<McpConnectionTestResult>;
}

/**
 * The organization's MCP servers.
 *
 * Shaped like `useMcpConnections` on purpose - the two managers do the same
 * job for different owners, and a reader who knows one should not have to
 * re-learn the other. What differs is only which endpoint it reads and which
 * cache key it owns.
 *
 * Personal management does not require `mcp:manage`. Its callers disable this
 * query without exposing cached organization records or waiting for a refusal.
 *
 * Mutations patch the cache directly so the list does not flicker; a test
 * refetches instead, because the probe writes `last_status` server-side and the
 * response says nothing about the row it changed.
 */
export function useOrgMcpConnections({
  enabled = true,
  retryOnMount = true,
}: { enabled?: boolean; retryOnMount?: boolean } = {}): UseOrgMcpConnectionsResult {
  const t = useTranslations("mcp");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const {
    data: connections = [],
    isLoading,
    isFetching,
    error: queryError,
    refetch,
  } = useQuery({
    queryKey: qk.mcpConnections.org(),
    queryFn: listOrgMcpConnections,
    enabled,
    retryOnMount,
  });

  const error = queryError ? getErrorMessage(queryError, tErrors, t("failedLoadOrgServers")) : null;

  const writeCache = useCallback(
    (updater: (prev: OrgMcpConnectionRecord[]) => OrgMcpConnectionRecord[]) => {
      queryClient.setQueryData<OrgMcpConnectionRecord[]>(qk.mcpConnections.org(), (prev = []) =>
        updater(prev),
      );
      void queryClient.invalidateQueries({ queryKey: qk.mcpServers.lists() });
      void queryClient.invalidateQueries({ queryKey: qk.mcpServers.entries() });
      // Account changes also change routine source ceilings and action inventories.
      void queryClient.invalidateQueries({ queryKey: qk.triggers.all() });
    },
    [queryClient],
  );

  const refresh = useCallback(async () => {
    if (!enabled) return;
    await Promise.all([
      refetch(),
      queryClient.invalidateQueries({ queryKey: qk.mcpServers.lists() }),
      queryClient.invalidateQueries({ queryKey: qk.mcpServers.entries() }),
      queryClient.invalidateQueries({ queryKey: qk.triggers.all() }),
    ]);
  }, [enabled, refetch, queryClient]);

  const create = useCallback<UseOrgMcpConnectionsResult["create"]>(
    async (input) => {
      const created = await createOrgMcpConnection(input);
      writeCache((prev) => [...prev, created]);
      return created;
    },
    [writeCache],
  );

  const update = useCallback<UseOrgMcpConnectionsResult["update"]>(
    async (id, patch) => {
      const updated = await updateOrgMcpConnection(id, patch);
      writeCache((prev) => prev.map((record) => (record.id === id ? updated : record)));
      return updated;
    },
    [writeCache],
  );

  const remove = useCallback<UseOrgMcpConnectionsResult["remove"]>(
    async (id) => {
      await deleteOrgMcpConnection(id);
      writeCache((prev) => prev.filter((record) => record.id !== id));
    },
    [writeCache],
  );

  const test = useCallback<UseOrgMcpConnectionsResult["test"]>(
    async (id) => {
      const result = await testOrgMcpConnection(id);
      await refresh();
      return result;
    },
    [refresh],
  );

  return {
    connections: enabled ? connections : [],
    isLoading: enabled && isLoading,
    isFetching: enabled && isFetching,
    error: enabled ? error : null,
    refresh,
    create,
    update,
    remove,
    test,
  };
}

/**
 * What agents asked one organization server to do, newest first (#2072).
 * Fetched only while somebody is looking, since the dialog showing it mounts on open.
 */
export function useOrgMcpToolCalls(connectionId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.mcpConnections.calls(connectionId),
    queryFn: () => listOrgMcpToolCalls(connectionId),
  });
  return { calls: data ?? [], isLoading, error };
}
