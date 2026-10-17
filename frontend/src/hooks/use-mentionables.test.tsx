import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useMentionables } from "./use-mentionables";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useMentionables", () => {
  it("reads what the agent offers as soon as there is an agent", async () => {
    const item = { kind: "skill", id: "s", name: "refunds" };
    vi.mocked(apiClient.get).mockResolvedValue({ items: [item], total: 1 });

    const { result } = renderHook(() => useMentionables("a-1"), { wrapper });
    await waitFor(() => expect(result.current.items).toEqual([item]));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a-1/mentionables", { params: undefined });
    expect(result.current.isError).toBe(false);
  });

  it("says it failed at once rather than retrying behind a loading line", async () => {
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockRejectedValue(new Error("500"));
    const client = new QueryClient();
    const { result } = renderHook(() => useMentionables("a-2"), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("reads the Builder's draft when the test panel runs it", async () => {
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { result } = renderHook(() => useMentionables("a-3", true), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a-3/mentionables", {
      params: { draft: "true" },
    });
  });

  it("asks nothing without an agent", () => {
    vi.mocked(apiClient.get).mockClear();
    renderHook(() => useMentionables(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
