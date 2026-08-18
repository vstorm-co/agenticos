import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePermissions } from "./use-permissions";
import { ApiError, apiClient } from "@/lib/api-client";
import { Perm } from "@/types/permissions";

// `ApiError` is the real class, not a stub: the hook's `retry` reads it to tell
// a refused organization (never retried) from a dropped connection (retried
// once), and a mocked-away class makes every rejection throw inside the retryer.
vi.mock("@/lib/api-client", async () => ({
  apiClient: { get: vi.fn() },
  ApiError: (await vi.importActual<typeof import("@/lib/api-error")>("@/lib/api-error")).ApiError,
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
    // And says the false is "not known": a caller that tells somebody what they
    // may not do has to tell the two apart.
    expect(result.current.isLoaded).toBe(false);
  });

  it("does not call the set loaded when the read failed", async () => {
    // `can()` answers false forever after a terminal failure, so anything that
    // reads that as "not granted" states a refusal the server never made. A 404
    // is the terminal one: the hook does not retry an organization the server
    // refuses.
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "no such organization"));
    const { result } = renderHook(() => usePermissions(), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());

    expect(result.current.isLoading).toBe(false);
    expect(result.current.can(Perm.agentsEdit)).toBe(false);
    expect(result.current.isLoaded).toBe(false);
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
    expect(result.current.isLoaded).toBe(true);
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
