import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRoleNavigation, useUpdateRoleNavigation } from "./use-role-navigation";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { RoleNavigationPolicy } from "@/types/role-navigation";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn() },
}));

const POLICY: RoleNavigationPolicy = {
  hidden_items: { owner: [], admin: [], builder: [], operator: [], member: [], viewer: [] },
  configurable_items: ["chat", "agents", "workflows"],
  editable_roles: ["admin", "builder", "operator", "member", "viewer"],
};
let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  vi.mocked(apiClient.get).mockResolvedValue(POLICY);
  vi.mocked(apiClient.patch).mockResolvedValue(POLICY);
});

describe("role sidebar policy", () => {
  it("pins the organization in the request and query cache", async () => {
    const { result } = renderHook(() => useRoleNavigation("org-a"), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(POLICY));
    expect(apiClient.get).toHaveBeenCalledWith("/roles/navigation", {
      headers: { "X-Organization-Id": "org-a" },
      signal: expect.any(AbortSignal),
    });
    expect(client.getQueryData(qk.organizations.roleNavigation("org-a"))).toEqual(POLICY);
  });

  it("waits until the page's organization is active", async () => {
    const { result } = renderHook(() => useRoleNavigation("org-b"), { wrapper });
    expect(result.current.isPending).toBe(true);
    expect(apiClient.get).not.toHaveBeenCalled();
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/roles/navigation",
      expect.objectContaining({
        headers: { "X-Organization-Id": "org-b" },
      }),
    );
  });

  it("surfaces a failed read and can retry", async () => {
    const failure = new Error("Policy unavailable");
    vi.mocked(apiClient.get).mockRejectedValueOnce(failure);
    const { result } = renderHook(() => useRoleNavigation("org-a"), { wrapper });
    await waitFor(() => expect(result.current.error).toBe(failure));
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.data).toEqual(POLICY));
    expect(result.current.error).toBeNull();
  });

  it("saves one role in the captured organization and refreshes its permissions", async () => {
    const saved = { ...POLICY, hidden_items: { ...POLICY.hidden_items, member: ["agents"] } };
    vi.mocked(apiClient.patch).mockResolvedValue(saved);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useUpdateRoleNavigation(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({
        organizationId: "org-a",
        role: "member",
        hiddenItems: ["agents"],
      });
    });
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/roles/navigation/member",
      {
        hidden_items: ["agents"],
      },
      { headers: { "X-Organization-Id": "org-a" } },
    );
    expect(client.getQueryData(qk.organizations.roleNavigation("org-a"))).toEqual(saved);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.organizations.permissions("org-a") });
    expect(client.getQueryData(qk.organizations.roleNavigation("org-b"))).toBeUndefined();
  });

  it("does not refill a cache after switching organization during a save", async () => {
    let resolve!: (value: RoleNavigationPolicy) => void;
    vi.mocked(apiClient.patch).mockReturnValue(
      new Promise<RoleNavigationPolicy>((done) => {
        resolve = done;
      }),
    );
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useUpdateRoleNavigation(), { wrapper });
    act(() =>
      result.current.mutate({ organizationId: "org-a", role: "member", hiddenItems: ["agents"] }),
    );
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await act(async () => {
      resolve(POLICY);
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).not.toHaveBeenCalled();
    expect(client.getQueryData(qk.organizations.roleNavigation("org-a"))).toBeUndefined();
    expect(client.getQueryData(qk.organizations.roleNavigation("org-b"))).toBeUndefined();
  });
});
