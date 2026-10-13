import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRetention } from "./use-retention";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const READ = {
  requested: { conversations: 3650 },
  effective: { conversations: 365, audit: 2190 },
  ceilings: { conversations: 365 },
  audit_floor_days: 2190,
  conflicts: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(READ);
  vi.mocked(apiClient.put).mockResolvedValue(READ);
});

describe("one organization's retention policy", () => {
  it("reads the organization in the path, not the active one", async () => {
    const { result } = renderHook(() => useRetention("o-1"), { wrapper });

    await waitFor(() => expect(result.current.policy).toEqual(READ));
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/retention");
  });

  it("writes the resolved policy back, so a period being cut is visible", async () => {
    // The response carries what was asked for *and* what the ceiling made of it.
    // Refetching instead would show the typed number until the round trip landed.
    const { result } = renderHook(() => useRetention("o-1"), { wrapper });
    await waitFor(() => expect(result.current.policy).toBeDefined());
    vi.mocked(apiClient.get).mockClear();

    await act(async () => {
      await result.current.save({ conversations: 3650 });
    });

    expect(apiClient.put).toHaveBeenCalledWith("/orgs/o-1/retention", {
      retention_days: { conversations: 3650 },
    });
    expect(result.current.policy?.effective.conversations).toBe(365);
  });
});
