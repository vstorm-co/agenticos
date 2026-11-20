import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import { useAppConnections } from "./use-app-connections";
import type { AppConnectionAuthorization, ConnectedAppDefinition } from "@/types/app-connections";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), patch: vi.fn() },
}));
const scope = { userId: "user-1", orgId: "org-1" };

function app(toolkit: string): ConnectedAppDefinition {
  return {
    key: `composio-${toolkit}`,
    toolkit,
    name: toolkit,
    description: `${toolkit} app`,
    category: "productivity",
    configured: true,
    availability: "ready",
    approval_required: false,
    action_count: 2,
    actions: [],
  };
}

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    user: {
      id: scope.userId,
      email: "one@example.test",
      is_active: true,
      created_at: "2026-01-01",
    },
  });
  useOrgStore.setState({ activeOrgId: scope.orgId });
  vi.mocked(apiClient.get).mockImplementation(async (url) =>
    url.endsWith("/catalog")
      ? { configured: true, catalog_available: true, apps: [], next_cursor: null }
      : { items: [], total: 0 },
  );
});

describe("useAppConnections", () => {
  it("uses the dedicated API and refreshes legacy connection observers after lifecycle changes", async () => {
    const { client, wrapper } = setup();
    const invalidated = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useAppConnections(scope), { wrapper });
    await waitFor(() => expect(result.current.connections.isSuccess).toBe(true));
    vi.mocked(apiClient.post).mockResolvedValue({ id: "connection" });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "connection" });
    await act(() => result.current.begin.mutateAsync({ toolkit: "gmail", label: "Work" }));
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/connect", {
      toolkit: "gmail",
      label: "Work",
    });
    await act(() =>
      result.current.begin.mutateAsync({ toolkit: "gmail", connectionId: "connection" }),
    );
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/connection/reconnect", {});
    await act(() => result.current.complete.mutateAsync({ session_uri: "session" }));
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/callback", {
      session_uri: "session",
    });
    await act(() => result.current.refreshConnection.mutateAsync("connection"));
    expect(apiClient.post).toHaveBeenCalledWith("/me/app-connections/connection/refresh", {});
    await act(() => result.current.setDefault.mutateAsync("connection"));
    expect(apiClient.patch).toHaveBeenCalledWith("/me/mcp-connections/connection", {
      is_default: true,
    });
    await act(() => result.current.remove.mutateAsync("connection"));
    expect(apiClient.delete).toHaveBeenCalledWith("/me/app-connections/connection");
    expect(invalidated).toHaveBeenCalledWith({ queryKey: qk.mcpConnections.all() });
    expect(invalidated).toHaveBeenCalledWith({
      queryKey: qk.appConnections.scope(scope.userId, scope.orgId),
    });
  });

  it.each(["organization", "user"] as const)(
    "rejects a late authorization response after a %s switch",
    async (kind) => {
      let resolve!: (value: AppConnectionAuthorization) => void;
      vi.mocked(apiClient.post).mockImplementation(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
      const { wrapper } = setup();
      const { result } = renderHook(() => useAppConnections(scope), { wrapper });
      await waitFor(() => expect(result.current.connections.isSuccess).toBe(true));
      let pending!: Promise<unknown>;
      act(() => {
        pending = result.current.begin
          .mutateAsync({ toolkit: "gmail" })
          .catch((error: unknown) => error);
      });
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledOnce());
      if (kind === "organization") useOrgStore.setState({ activeOrgId: "org-2" });
      else
        useAuthStore.setState({
          user: {
            id: "user-2",
            email: "two@example.test",
            is_active: true,
            created_at: "2026-01-01",
          },
        });
      await act(async () => {
        resolve({
          connection_id: "c",
          attempt_id: "a",
          redirect_url: "https://connect.example",
          expires_at: "2026-01-01",
        });
      });
      expect(await pending).toMatchObject({ name: "AbortError" });
      await act(async () => {
        await expect(result.current.begin.mutateAsync({ toolkit: "gmail" })).rejects.toMatchObject({
          name: "AbortError",
        });
      });
      expect(apiClient.post).toHaveBeenCalledOnce();
    },
  );

  it("searches and paginates catalog pages while deduplicating apps by key", async () => {
    const gmail = app("gmail");
    const linear = app("linear");
    let catalogCalls = 0;
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (!url.endsWith("/catalog")) return { items: [], total: 0 };
      catalogCalls += 1;
      return catalogCalls === 1
        ? {
            configured: true,
            catalog_available: true,
            apps: [gmail],
            next_cursor: "catalog-page-2",
          }
        : {
            configured: true,
            catalog_available: true,
            apps: [gmail, linear],
            next_cursor: null,
          };
    });

    const { wrapper } = setup();
    const { result } = renderHook(() => useAppConnections(scope, "linear"), { wrapper });
    await waitFor(() => expect(result.current.catalog.data?.apps).toEqual([gmail]));
    expect(result.current.catalog.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.catalog.fetchNextPage();
    });

    await waitFor(() => expect(result.current.catalog.data?.apps).toEqual([gmail, linear]));
    expect(result.current.catalog.data?.next_cursor).toBeNull();
    expect(result.current.catalog.hasNextPage).toBe(false);
    expect(apiClient.get).toHaveBeenCalledWith(
      "/me/app-connections/catalog",
      expect.objectContaining({ params: { limit: "24", search: "linear" } }),
    );
    expect(apiClient.get).toHaveBeenCalledWith(
      "/me/app-connections/catalog",
      expect.objectContaining({
        params: { limit: "24", search: "linear", cursor: "catalog-page-2" },
      }),
    );
  });

  it("keeps account loading independent when the app catalog fails", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("/catalog")) throw new Error("catalog unavailable");
      return { items: [{ id: "existing-account" }], total: 1 };
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useAppConnections(scope), { wrapper });

    await waitFor(() => expect(result.current.catalog.isError).toBe(true));
    await waitFor(() => expect(result.current.connections.isSuccess).toBe(true));
    expect(result.current.connections.data).toEqual([{ id: "existing-account" }]);
  });

  it("does not publish a previous workspace's late account list", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("/catalog"))
        return { configured: true, catalog_available: true, apps: [], next_cursor: null };
      return new Promise((done) => {
        resolve = done;
      });
    });
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useAppConnections(scope), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    useOrgStore.setState({ activeOrgId: "org-2" });
    await act(async () => resolve({ items: [{ identity: "private@example.test" }], total: 1 }));
    await waitFor(() => expect(result.current.connections.isError).toBe(true));
    expect(client.getQueryData(qk.appConnections.list(scope.userId, scope.orgId))).toBeUndefined();
  });

  it.each(["organization", "user"] as const)(
    "does not refresh a scope left by the %s",
    async (boundary) => {
      const { client, wrapper } = setup();
      const { result } = renderHook(() => useAppConnections(scope), { wrapper });
      await waitFor(() => expect(result.current.connections.isSuccess).toBe(true));
      const invalidate = vi.spyOn(client, "invalidateQueries");
      const reads = vi.mocked(apiClient.get).mock.calls.length;

      if (boundary === "organization") useOrgStore.setState({ activeOrgId: "org-2" });
      else
        useAuthStore.setState({
          user: {
            id: "user-2",
            email: "two@example.test",
            is_active: true,
            created_at: "2026-01-01",
          },
        });
      await act(async () => result.current.refresh());

      expect(invalidate).not.toHaveBeenCalled();
      expect(apiClient.get).toHaveBeenCalledTimes(reads);
      expect(
        client.getQueryState(qk.appConnections.list(scope.userId, scope.orgId))?.isInvalidated,
      ).toBe(false);
    },
  );
});
