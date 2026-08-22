import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrgTriggers } from "./use-org-triggers";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * The organization-wide list behind the sidebar section and the Activity tab.
 *
 * Read-only by design - the writes live in `useTriggers` - so what is worth
 * asserting is that it reads the org endpoint, that it holds until it is enabled,
 * and that a failed request is reported rather than rendered as "no triggers".
 */
describe("useOrgTriggers", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the organization-wide endpoint, paginated", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/triggers?skip=0&limit=100");
  });

  it("gathers every page when the total exceeds one page", async () => {
    // A page is capped at the server limit; without walking it, the tail - the
    // older rows a listing with no next-page control can never reach - is lost.
    const page = (start: number, count: number, total: number) => ({
      items: Array.from({ length: count }, (_, index) => ({ id: `t${start + index}` })),
      total,
    });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce(page(0, 100, 150))
      .mockResolvedValueOnce(page(100, 50, 150));
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.triggers).toHaveLength(150);
    expect(result.current.total).toBe(150);
    expect(apiClient.get).toHaveBeenNthCalledWith(1, "/triggers?skip=0&limit=100");
    expect(apiClient.get).toHaveBeenNthCalledWith(2, "/triggers?skip=100&limit=100");
  });

  it("stops after a full page that already reaches the total", async () => {
    // A page filled to the limit that has collected every row must not ask for a
    // second, empty page - the total, not only a short page, ends the walk.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: Array.from({ length: 100 }, (_, index) => ({ id: `t${index}` })),
      total: 100,
    });
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.triggers).toHaveLength(100);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("does not fetch while it is disabled", () => {
    renderHook(() => useOrgTriggers(false), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("returns the rows and the total the server reports", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "t1", agent_name: "Nightly" }],
      total: 1,
    });
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.total).toBe(1);
    expect(result.current.triggers).toHaveLength(1);
  });

  it("reports a failed request instead of an empty list", async () => {
    // An empty page and a 502 are the same pixels; the surface must be able to
    // tell them apart, so the error is not swallowed into "no triggers yet".
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.triggers).toHaveLength(0);
  });
});
