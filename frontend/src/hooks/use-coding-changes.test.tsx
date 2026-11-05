import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCodingChanges } from "./use-coding-changes";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe("what one coding task changed", () => {
  it("reads the change set the report names", async () => {
    const changes = { id: "c-1", files: [], omitted: 0, truncated: false };
    vi.mocked(apiClient.get).mockResolvedValue(changes);

    const { result } = renderHook(() => useCodingChanges("c-1"), { wrapper });

    await waitFor(() => expect(result.current.changes).toEqual(changes));
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/coding-changes/c-1");
    expect(result.current.failed).toBe(false);
  });

  it("says it failed, once, for a change set the reader may not see", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "Change set not found"));

    const { result } = renderHook(() => useCodingChanges("c-2"), { wrapper });

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.changes).toBeNull();
    // A 404 is an answer, not a blip: asking again would not change it.
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("asks again after a blip, so a panel does not stay empty once the server is back", async () => {
    const changes = { id: "c-3", files: [], omitted: 0, truncated: false };
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new ApiError(503, "Service unavailable"))
      .mockResolvedValueOnce(changes);

    const { result } = renderHook(() => useCodingChanges("c-3"), { wrapper });

    await waitFor(() => expect(result.current.changes).toEqual(changes));
    expect(result.current.failed).toBe(false);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("asks once more after a dropped connection, then says it failed", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useCodingChanges("c-4"), { wrapper });

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });
});
