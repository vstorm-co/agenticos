"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  createOrgMcpConnection,
  deleteOrgMcpConnection,
  listOrgMcpConnections,
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
 * `enabled: false` is not offered: a caller without `connections:manage` gets a
 * 403 from the backend, which surfaces as `error` and is a truer thing to show
 * than an empty list that reads as "your organization has none".
 *
 * Mutations patch the cache directly so the list does not flicker; a test
 * refetches instead, because the probe writes `last_status` server-side and the
 * response says nothing about the row it changed.
 */
export function useOrgMcpConnections(): UseOrgMcpConnectionsResult {
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
  });

  const error = queryError ? getErrorMessage(queryError, tErrors, t("failedLoadOrgServers")) : null;

  const writeCache = useCallback(
    (updater: (prev: OrgMcpConnectionRecord[]) => OrgMcpConnectionRecord[]) =>
      queryClient.setQueryData<OrgMcpConnectionRecord[]>(qk.mcpConnections.org(), (prev = []) =>
        updater(prev),
      ),
    [queryClient],
  );

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

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
      await refetch();
      return result;
    },
    [refetch],
  );

  return { connections, isLoading, isFetching, error, refresh, create, update, remove, test };
}
