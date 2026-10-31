import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTableRecords } from "./use-table-records";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { post: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useTableRecords", () => {
  it("is disabled when no table id is given", () => {
    const { result } = renderHook(() => useTableRecords(null, { skip: 0, limit: 50 }), {
      wrapper,
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.records).toEqual([]);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("queries records with the given filters and reads has_more", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      items: [{ id: "r1" }],
      skip: 0,
      limit: 50,
      has_more: true,
    });
    const query = {
      filters: [],
      sort: { by: "created_at", direction: "asc" as const },
      skip: 0,
      limit: 50,
    };
    const { result } = renderHook(() => useTableRecords("t1", query), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records/query", query);
    expect(result.current.records).toHaveLength(1);
    expect(result.current.hasMore).toBe(true);
  });
});
