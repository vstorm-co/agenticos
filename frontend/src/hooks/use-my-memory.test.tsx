import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMyMemory } from "./use-my-memory";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PAGE = {
  items: [{ id: "n-1", name: "prefs", deactivated_at: null }],
  total: 1,
  external_stores: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(PAGE);
  vi.mocked(apiClient.patch).mockResolvedValue(PAGE.items[0]);
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

describe("the caller's own memory", () => {
  it("reads it on mount", async () => {
    const { result } = renderHook(() => useMyMemory(), { wrapper });

    await waitFor(() => expect(result.current.page).toEqual(PAGE));
  });

  it("refetches after suppressing, so the badge follows the server", async () => {
    const { result } = renderHook(() => useMyMemory(), { wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());
    vi.mocked(apiClient.get).mockClear();

    await act(async () => {
      await result.current.setActive("n-1", false);
    });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
  });

  it("refetches after a delete", async () => {
    const { result } = renderHook(() => useMyMemory(), { wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());
    vi.mocked(apiClient.get).mockClear();

    await act(async () => {
      await result.current.remove("n-1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/memory/mine/n-1");
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
  });
});
