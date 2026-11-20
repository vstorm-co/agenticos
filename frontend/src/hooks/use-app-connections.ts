"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  completeAppConnection,
  connectApp,
  disconnectApp,
  getAppConnectionCatalog,
  listAppConnections,
  reconnectApp,
  refreshAppConnection,
} from "@/lib/app-connections-api";
import { updateMcpConnection } from "@/lib/mcp-connections-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import type { AppConnectionCallback, AppConnectionScope } from "@/types/app-connections";

export function isCurrentAppConnectionScope(scope: AppConnectionScope): boolean {
  return (
    useAuthStore.getState().user?.id === scope.userId &&
    useOrgStore.getState().activeOrgId === scope.orgId
  );
}

/** Account switches must not publish stale data or follow a previous user's consent URL. */
export function useAppConnections(scope: AppConnectionScope, search = "") {
  const client = useQueryClient();
  const key = qk.appConnections.scope(scope.userId, scope.orgId);
  async function inScope<T>(run: () => Promise<T>): Promise<T> {
    if (!isCurrentAppConnectionScope(scope)) throw new DOMException("scope_changed", "AbortError");
    const result = await run();
    if (!isCurrentAppConnectionScope(scope)) throw new DOMException("scope_changed", "AbortError");
    return result;
  }
  const catalog = useInfiniteQuery({
    queryKey: qk.appConnections.catalog(scope.userId, scope.orgId, search),
    queryFn: ({ signal, pageParam }) =>
      inScope(() => getAppConnectionCatalog(signal, search, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last, _pages, _lastParam, params) =>
      last.next_cursor && !params.includes(last.next_cursor) ? last.next_cursor : undefined,
    retry: false,
  });
  const connections = useQuery({
    queryKey: qk.appConnections.list(scope.userId, scope.orgId),
    queryFn: ({ signal }) => inScope(() => listAppConnections(signal)),
    // Authorization is completed outside this tab; do not reuse a long freshness window.
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
  async function invalidate() {
    if (!isCurrentAppConnectionScope(scope)) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: qk.mcpConnections.all() }),
      client.invalidateQueries({ queryKey: qk.mcpServers.lists() }),
      client.invalidateQueries({ queryKey: qk.mcpServers.entries() }),
    ]);
  }
  const begin = useMutation({
    mutationFn: (input: { toolkit: string; label?: string; connectionId?: string }) =>
      inScope(() =>
        input.connectionId
          ? reconnectApp(input.connectionId)
          : connectApp({ toolkit: input.toolkit, ...(input.label ? { label: input.label } : {}) }),
      ),
    onSuccess: invalidate,
  });
  const complete = useMutation({
    mutationFn: (input: AppConnectionCallback) => inScope(() => completeAppConnection(input)),
    onSuccess: invalidate,
  });
  const refreshConnection = useMutation({
    mutationFn: (id: string) => inScope(() => refreshAppConnection(id)),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => inScope(() => disconnectApp(id)),
    onSuccess: invalidate,
  });
  const setDefault = useMutation({
    mutationFn: (id: string) => inScope(() => updateMcpConnection(id, { is_default: true })),
    onSuccess: invalidate,
  });
  const enable = useMutation({
    mutationFn: (id: string) => inScope(() => updateMcpConnection(id, { is_enabled: true })),
    onSuccess: invalidate,
  });
  return {
    catalog: {
      ...catalog,
      data: catalog.data
        ? {
            ...catalog.data.pages[0],
            catalog_available: catalog.data.pages.every((page) => page.catalog_available),
            apps: [
              ...new Map(
                catalog.data.pages.flatMap((page) => page.apps).map((app) => [app.key, app]),
              ).values(),
            ],
            next_cursor: catalog.data.pages.at(-1)?.next_cursor ?? null,
          }
        : undefined,
    },
    connections,
    begin,
    complete,
    refreshConnection,
    remove,
    setDefault,
    enable,
    refresh: invalidate,
  };
}
