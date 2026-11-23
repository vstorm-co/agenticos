import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  NetworkConnectionScopeKey,
} from "@/types/network-connections";
import {
  isCurrentNetworkConnectionScope,
  useNetworkConnectionState,
  useNetworkConnections,
  useNetworkPeers,
} from "./use-network-connections";

const storeState = vi.hoisted(() => ({
  user: { id: "user-1" } as { id: string } | null,
  orgId: "org-1" as string | null,
}));

vi.mock("@/lib/network-connections-api", () => ({
  connectNetworkConnection: vi.fn(),
  createNetworkConnection: vi.fn(),
  getNetworkConnection: vi.fn(),
  listNetworkConnections: vi.fn(),
  listNetworkPeers: vi.fn(),
  pauseNetworkConnection: vi.fn(),
  refreshNetworkConnection: vi.fn(),
  revokeNetworkConnection: vi.fn(),
}));
vi.mock("@/stores", () => {
  const useAuthStore = Object.assign(
    (selector: (state: { user: typeof storeState.user }) => unknown) =>
      selector({ user: storeState.user }),
    {
      getState: () => ({ user: storeState.user }),
      setState: (next: { user?: typeof storeState.user }) => {
        if ("user" in next) storeState.user = next.user ?? null;
      },
    },
  );
  const useOrgStore = Object.assign(
    (selector: (state: { activeOrgId: typeof storeState.orgId }) => unknown) =>
      selector({ activeOrgId: storeState.orgId }),
    {
      getState: () => ({ activeOrgId: storeState.orgId }),
      setState: (next: { activeOrgId?: typeof storeState.orgId }) => {
        if ("activeOrgId" in next) storeState.orgId = next.activeOrgId ?? null;
      },
    },
  );
  return { useAuthStore, useOrgStore };
});

const scope: NetworkConnectionScopeKey = { userId: "user-1", orgId: "org-1" };
const connection: NetworkConnection = {
  id: "conn-1",
  organization_id: scope.orgId,
  owner_user_id: scope.userId,
  scope: "user",
  name: "Laptop",
  desired_state: "active",
  auth_state: "authenticated",
  runtime_state: "running",
  cleanup_state: "none",
  tailnet_name: null,
  node_id: null,
  last_seen_at: null,
  last_error_code: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  can_manage: true,
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function setScope(userId: string | null = scope.userId, orgId: string | null = scope.orgId) {
  useAuthStore.setState({ user: userId ? ({ id: userId } as never) : null });
  useOrgStore.setState({ activeOrgId: orgId });
}

beforeEach(() => {
  vi.resetAllMocks();
  storeState.user = { id: "user-1" };
  storeState.orgId = "org-1";
  setScope();
});

describe("useNetworkConnections", () => {
  it("updates the current page for create, connect, pause, refresh and revoke", async () => {
    const client = makeClient();
    const key = qk.networkConnections.list(scope.userId, scope.orgId, 0, 50);
    client.setQueryData<NetworkConnectionList>(key, {
      items: [connection],
      total: 1,
      available: true,
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    const { result } = renderHook(() => useNetworkConnections({ enabled: false }), {
      wrapper: wrapper(client),
    });
    await act(async () => result.current.invalidate());

    const created = { ...connection, id: "conn-2", name: "Tablet" };
    vi.mocked(createNetworkConnection).mockResolvedValue(created);
    await act(async () => {
      await result.current.create({ name: created.name, scope: "org" });
    });
    expect(client.getQueryData<NetworkConnectionList>(key)?.items).toEqual([created, connection]);
    expect(
      client.getQueryData(qk.networkConnections.detail(scope.userId, scope.orgId, "conn-2")),
    ).toEqual(created);

    const connected = { ...connection, runtime_state: "starting" as const };
    vi.mocked(connectNetworkConnection).mockResolvedValue(connected);
    await act(async () => {
      await result.current.connect(connection.id);
    });
    expect(client.getQueryData<NetworkConnectionList>(key)?.items[1]).toEqual(connected);

    const paused = { ...connection, desired_state: "paused" as const };
    vi.mocked(pauseNetworkConnection).mockResolvedValue(paused);
    await act(async () => {
      await result.current.pause(connection.id);
    });
    expect(client.getQueryData<NetworkConnectionList>(key)?.items[1]).toEqual(paused);

    vi.mocked(refreshNetworkConnection).mockResolvedValue(connection);
    await act(async () => {
      await result.current.refreshStatus(connection.id);
    });

    const revoked = { ...connection, desired_state: "revoked" as const };
    vi.mocked(revokeNetworkConnection).mockResolvedValue(revoked);
    await act(async () => {
      await result.current.revoke(connection.id);
    });
    expect(client.getQueryData<NetworkConnectionList>(key)?.items[1]).toEqual(revoked);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: qk.networkConnections.list(scope.userId, scope.orgId),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: qk.networkConnections.detail(scope.userId, scope.orgId, connection.id),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: qk.networkConnections.peers(scope.userId, scope.orgId, connection.id),
    });
  });

  it("leaves later pages unchanged and writes a detail when the page is not cached", () => {
    const client = makeClient();
    const laterKey = qk.networkConnections.list(scope.userId, scope.orgId, 50, 50);
    const page: NetworkConnectionList = { items: [connection], total: 80, available: true };
    client.setQueryData(laterKey, page);
    const { result } = renderHook(() => useNetworkConnections({ enabled: false, skip: 50 }), {
      wrapper: wrapper(client),
    });
    const added = { ...connection, id: "conn-2" };

    act(() => result.current.updateCachedConnection(added));

    expect(client.getQueryData(laterKey)).toEqual(page);
    expect(
      client.getQueryData(qk.networkConnections.detail(scope.userId, scope.orgId, added.id)),
    ).toEqual(added);

    const emptyClient = makeClient();
    const emptyHook = renderHook(() => useNetworkConnections({ enabled: false }), {
      wrapper: wrapper(emptyClient),
    });
    act(() => emptyHook.result.current.updateCachedConnection(connection));
    expect(
      emptyClient.getQueryData(qk.networkConnections.list(scope.userId, scope.orgId, 0, 50)),
    ).toBeUndefined();
  });

  it("does not touch cached data after the reader's organization changes", async () => {
    const client = makeClient();
    const key = qk.networkConnections.list(scope.userId, scope.orgId, 0, 50);
    client.setQueryData<NetworkConnectionList>(key, {
      items: [connection],
      total: 1,
      available: true,
    });
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    const { result } = renderHook(() => useNetworkConnections({ enabled: false }), {
      wrapper: wrapper(client),
    });

    act(() => setScope(scope.userId, "org-2"));
    act(() => {
      result.current.updateCachedConnection({ ...connection, name: "Changed" });
    });
    await act(async () => result.current.invalidate(connection.id));

    expect(client.getQueryData<NetworkConnectionList>(key)?.items).toEqual([connection]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("aborts an in-flight mutation when the active organization changes", async () => {
    const client = makeClient();
    const { result } = renderHook(() => useNetworkConnections({ enabled: false }), {
      wrapper: wrapper(client),
    });
    let finish!: (value: NetworkConnection) => void;
    vi.mocked(connectNetworkConnection).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    let error: unknown;

    await act(async () => {
      const pending = result.current.connect(connection.id);
      await waitFor(() => expect(connectNetworkConnection).toHaveBeenCalledOnce());
      setScope(scope.userId, "org-2");
      finish(connection);
      try {
        await pending;
      } catch (cause) {
        error = cause;
      }
    });

    expect(error).toMatchObject({ name: "AbortError" });
  });

  it("refuses writes and invalidation when no identity scope exists", async () => {
    setScope(null, null);
    const client = makeClient();
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
    const { result } = renderHook(() => useNetworkConnections({ enabled: false }), {
      wrapper: wrapper(client),
    });

    await expect(result.current.create({ name: "Laptop", scope: "user" })).rejects.toMatchObject({
      name: "AbortError",
    });
    act(() => result.current.updateCachedConnection(connection));
    await act(async () => result.current.invalidate(connection.id));

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("loads the list through its guarded scope and can refresh it", async () => {
    const client = makeClient();
    const list: NetworkConnectionList = { items: [connection], total: 1, available: true };
    vi.mocked(listNetworkConnections).mockResolvedValue(list);
    const { result } = renderHook(() => useNetworkConnections(), { wrapper: wrapper(client) });

    await waitFor(() => expect(result.current.connections).toEqual([connection]));
    await act(async () => {
      await result.current.refresh();
    });

    expect(listNetworkConnections).toHaveBeenCalledWith(0, 50, expect.any(AbortSignal));
  });
});

describe("scoped connection detail and peers", () => {
  it("reads detail and peer data, then refuses them after scope changes", async () => {
    const client = makeClient();
    vi.mocked(getNetworkConnection).mockResolvedValue(connection);
    vi.mocked(listNetworkPeers).mockResolvedValue({ items: [], observed_at: null });
    const detail = renderHook(() => useNetworkConnectionState(connection.id, true, scope), {
      wrapper: wrapper(client),
    });
    const peers = renderHook(() => useNetworkPeers(connection.id, scope, true), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(detail.result.current.data).toEqual(connection));
    await waitFor(() =>
      expect(peers.result.current.data).toEqual({ items: [], observed_at: null }),
    );
    expect(getNetworkConnection).toHaveBeenCalledWith(connection.id, expect.any(AbortSignal));
    expect(listNetworkPeers).toHaveBeenCalledWith(connection.id, expect.any(AbortSignal));

    act(() => setScope(scope.userId, "org-2"));
    detail.rerender();
    peers.rerender();
    let detailResult!: Awaited<ReturnType<typeof detail.result.current.refetch>>;
    let peersResult!: Awaited<ReturnType<typeof peers.result.current.refetch>>;
    await act(async () => {
      detailResult = await detail.result.current.refetch();
      peersResult = await peers.result.current.refetch();
    });
    expect(detailResult.error).toMatchObject({ name: "AbortError" });
    expect(peersResult.error).toMatchObject({ name: "AbortError" });
    expect(getNetworkConnection).toHaveBeenCalledTimes(1);
    expect(listNetworkPeers).toHaveBeenCalledTimes(1);
  });

  it("recognizes only the current user and organization pair", () => {
    expect(isCurrentNetworkConnectionScope(scope)).toBe(true);
    act(() => setScope("user-2", scope.orgId));
    expect(isCurrentNetworkConnectionScope(scope)).toBe(false);
  });

  it.each(["expired", "error"] as const)(
    "stops polling when authorization is %s",
    async (authState) => {
      const client = makeClient();
      vi.mocked(getNetworkConnection).mockResolvedValue({ ...connection, auth_state: authState });
      const { result } = renderHook(() => useNetworkConnectionState(connection.id, true, scope), {
        wrapper: wrapper(client),
      });

      await waitFor(() => expect(result.current.data?.auth_state).toBe(authState));
    },
  );

  it("uses empty cache keys and refuses queries without a complete scope", async () => {
    setScope(null, null);
    const client = makeClient();
    const detail = renderHook(() => useNetworkConnectionState(null, true, null), {
      wrapper: wrapper(client),
    });
    const missingDetailScope = renderHook(
      () => useNetworkConnectionState(connection.id, true, null),
      { wrapper: wrapper(client) },
    );
    const peers = renderHook(() => useNetworkPeers(connection.id, null, true), {
      wrapper: wrapper(client),
    });

    let detailResult!: Awaited<ReturnType<typeof detail.result.current.refetch>>;
    let missingScopeResult!: Awaited<ReturnType<typeof missingDetailScope.result.current.refetch>>;
    let peersResult!: Awaited<ReturnType<typeof peers.result.current.refetch>>;
    await act(async () => {
      detailResult = await detail.result.current.refetch();
      missingScopeResult = await missingDetailScope.result.current.refetch();
      peersResult = await peers.result.current.refetch();
    });

    expect(detailResult.error).toMatchObject({ name: "AbortError" });
    expect(missingScopeResult.error).toMatchObject({ name: "AbortError" });
    expect(peersResult.error).toMatchObject({ name: "AbortError" });
    expect(getNetworkConnection).not.toHaveBeenCalled();
    expect(listNetworkPeers).not.toHaveBeenCalled();
  });
});
