import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAdminOrganizationDetail } from "./use-admin-organization-detail";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockResolvedValue({
    id: "org-1",
    name: "Acme",
    slug: "acme",
    is_personal: false,
    member_count: 2,
    agent_count: 1,
    owner_user_id: "u1",
    owner_email: "owner@example.com",
    owner_name: "Owner",
    created_at: "2026-07-01T00:00:00Z",
    monthly_budget_usd: "50.000000",
    members: [{ user_id: "u1", email: "owner@example.com", name: "Owner", role: "owner" }],
  });
});

describe("useAdminOrganizationDetail", () => {
  it("reads one tenant by id, with its members and roles", async () => {
    const { result } = renderHook(() => useAdminOrganizationDetail("org-1"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/admin/organizations/org-1");
    expect(result.current.organization?.name).toBe("Acme");
    expect(result.current.organization?.members[0]?.role).toBe("owner");
  });

  it("fetches nothing while disabled, so a closed drawer is quiet", async () => {
    const { result } = renderHook(() => useAdminOrganizationDetail("org-1", { enabled: false }), {
      wrapper,
    });

    expect(result.current.organization).toBeUndefined();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
