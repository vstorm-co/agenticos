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

  it("reads the organization-wide endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useOrgTriggers(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/triggers");
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
