"use client";

import { useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  connectNetworkConnection,
  createNetworkConnection,
  getNetworkConnection,
  listNetworkConnections,
  listNetworkPeers,
  pauseNetworkConnection,
  refreshNetworkConnection,
  revokeNetworkConnection,
} from "@/lib/network-connections-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import type {
  NetworkConnection,
  NetworkConnectionList,
  NetworkConnectionScope,
  NetworkConnectionScopeKey,
} from "@/types/network-connections";

export type { NetworkConnectionScopeKey } from "@/types/network-connections";

export function isCurrentNetworkConnectionScope(scope: NetworkConnectionScopeKey): boolean {
  return (
    useAuthStore.getState().user?.id === scope.userId &&
    useOrgStore.getState().activeOrgId === scope.orgId
  );
}

export function useNetworkConnections(
  options: { enabled?: boolean; skip?: number; limit?: number } = {},
) {
  const client = useQueryClient();
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const scope = useMemo(() => (userId && orgId ? { userId, orgId } : null), [userId, orgId]);
  const enabled = (options.enabled ?? true) && Boolean(scope);
  const skip = options.skip ?? 0;
  const limit = options.limit ?? 50;
  const listRootKey = useMemo(
    () => qk.networkConnections.list(userId ?? "", orgId),
    [userId, orgId],
  );
  const listKey = useMemo(
    () => qk.networkConnections.list(userId ?? "", orgId, skip, limit),
    [userId, orgId, skip, limit],
  );

  async function inScope<T>(run: () => Promise<T>): Promise<T> {
    if (!scope || !isCurrentNetworkConnectionScope(scope)) {
      throw new DOMException("scope_changed", "AbortError");
    }
    const result = await run();
    if (!isCurrentNetworkConnectionScope(scope)) {
      throw new DOMException("scope_changed", "AbortError");
    }
    return result;
  }

  const invalidate = useCallback(
    async (id?: string) => {
      if (!scope || !isCurrentNetworkConnectionScope(scope)) return;
      await Promise.all([
        client.invalidateQueries({ queryKey: listRootKey }),
        ...(id
          ? [
              client.invalidateQueries({
                queryKey: qk.networkConnections.detail(userId ?? "", orgId, id),
              }),
              client.invalidateQueries({
                queryKey: qk.networkConnections.peers(userId ?? "", orgId, id),
              }),
            ]
          : []),
      ]);
    },
    [client, listRootKey, orgId, scope, userId],
  );

  const updateCachedConnection = useCallback(
    (connection: NetworkConnection) => {
      if (!scope || !isCurrentNetworkConnectionScope(scope)) return;
      client.setQueryData<NetworkConnectionList>(listKey, (old) => {
        if (!old) return undefined;
        const exists = old.items.some((item) => item.id === connection.id);
        if (!exists && skip > 0) return old;
        return {
          ...old,
          items: exists
            ? old.items.map((item) => (item.id === connection.id ? connection : item))
            : [connection, ...old.items],
          total: exists ? old.total : old.total + 1,
        };
      });
      client.setQueryData(
        qk.networkConnections.detail(scope.userId, scope.orgId, connection.id),
        connection,
      );
    },
    [client, listKey, scope, skip],
  );

  const list = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) => inScope(() => listNetworkConnections(skip, limit, signal)),
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const createMutation = useMutation({
    mutationFn: (input: { name: string; scope: NetworkConnectionScope }) =>
      inScope(() => createNetworkConnection(input)),
    onSuccess: (connection) => {
      updateCachedConnection(connection);
      void invalidate(connection.id);
    },
  });
  const connectMutation = useMutation({
    mutationFn: (id: string) => inScope(() => connectNetworkConnection(id)),
    onSuccess: (connection) => {
      updateCachedConnection(connection);
      void invalidate(connection.id);
    },
  });
  const pauseMutation = useMutation({
    mutationFn: (id: string) => inScope(() => pauseNetworkConnection(id)),
    onSuccess: (connection) => {
      updateCachedConnection(connection);
      void invalidate(connection.id);
    },
  });
  const refreshMutation = useMutation({
    mutationFn: (id: string) => inScope(() => refreshNetworkConnection(id)),
    onSuccess: (connection) => {
      updateCachedConnection(connection);
      void invalidate(connection.id);
    },
  });
  const revokeMutation = useMutation({
    mutationFn: (id: string) => inScope(() => revokeNetworkConnection(id)),
    onSuccess: (connection) => {
      updateCachedConnection(connection);
      void invalidate(connection.id);
    },
  });

  return {
    scope,
    connections: list.data?.items ?? [],
    total: list.data?.total ?? 0,
    available: list.data?.available ?? null,
    error: list.error,
    isLoading: list.isLoading,
    isFetching: list.isFetching,
    isCreating: createMutation.isPending,
    isRefreshing: refreshMutation.isPending || pauseMutation.isPending || revokeMutation.isPending,
    create: createMutation.mutateAsync,
    connect: connectMutation.mutateAsync,
    pause: pauseMutation.mutateAsync,
    refreshStatus: refreshMutation.mutateAsync,
    revoke: revokeMutation.mutateAsync,
    updateCachedConnection,
    refresh: () => list.refetch(),
    invalidate,
  };
}

export function useNetworkConnectionState(
  id: string | null,
  enabled: boolean,
  scope: NetworkConnectionScopeKey | null,
) {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const current = Boolean(
    enabled && id && scope && scope.userId === userId && scope.orgId === orgId,
  );
  return useQuery({
    queryKey: qk.networkConnections.detail(userId ?? "", orgId, id ?? ""),
    queryFn: ({ signal }) => {
      if (!id || !scope || !isCurrentNetworkConnectionScope(scope)) {
        throw new DOMException("scope_changed", "AbortError");
      }
      return getNetworkConnection(id, signal);
    },
    enabled: current,
    refetchInterval: (query) => {
      if (!current) return false;
      const connection = query.state.data;
      return connection &&
        (connection.auth_state === "authenticated" ||
          connection.auth_state === "expired" ||
          connection.auth_state === "error") &&
        connection.runtime_state !== "starting"
        ? false
        : 5000;
    },
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useNetworkPeers(
  id: string,
  scope: NetworkConnectionScopeKey | null,
  enabled: boolean,
) {
  const userId = useAuthStore((state) => state.user?.id);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const current = Boolean(enabled && scope && scope.userId === userId && scope.orgId === orgId);
  return useQuery({
    queryKey: qk.networkConnections.peers(userId ?? "", orgId, id),
    queryFn: ({ signal }) => {
      if (!scope || !isCurrentNetworkConnectionScope(scope)) {
        throw new DOMException("scope_changed", "AbortError");
      }
      return listNetworkPeers(id, signal);
    },
    enabled: current,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
