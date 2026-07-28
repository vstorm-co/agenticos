import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePermissions } from "./use-permissions";
import { apiClient } from "@/lib/api-client";
import { Perm } from "@/types/permissions";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("usePermissions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("returns false while permissions are loading", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => usePermissions(), { wrapper });
    // Revealing an action later is fine; briefly offering one that would be
    // refused is not.
    expect(result.current.can(Perm.agentsEdit)).toBe(false);
  });

  it("reports a permission the caller holds", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      organization_id: "org-1",
      role: "builder",
      is_app_admin: false,
      permissions: [{ permission: "agents:edit", scope: "shared" }],
    });
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.can(Perm.agentsEdit)).toBe(true);
    expect(result.current.can(Perm.membersManage)).toBe(false);
    expect(result.current.role).toBe("builder");
  });

  it("exposes the scope, because which rows matters as much as whether", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      organization_id: "org-1",
      role: "member",
      is_app_admin: false,
      permissions: [{ permission: "agents:edit", scope: "own" }],
    });
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.scopeOf(Perm.agentsEdit)).toBe("own");
    expect(result.current.scopeOf(Perm.membersManage)).toBe("none");
  });

  it("requires every permission for canAll", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      organization_id: "org-1",
      role: "operator",
      is_app_admin: false,
      permissions: [
        { permission: "agents:view", scope: "all" },
        { permission: "agents:run", scope: "all" },
      ],
    });
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.canAll(Perm.agentsView, Perm.agentsRun)).toBe(true);
    expect(result.current.canAll(Perm.agentsView, Perm.agentsEdit)).toBe(false);
  });

  it("surfaces the platform superadmin flag", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      organization_id: "org-1",
      role: "viewer",
      is_app_admin: true,
      permissions: [],
    });
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAppAdmin).toBe(true);
  });
});
