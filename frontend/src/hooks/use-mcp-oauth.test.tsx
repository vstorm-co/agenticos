import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConnectedApps, useConsentRequest } from "./use-mcp-oauth";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useConsentRequest", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the request and answers it either way", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ request_id: "r1", client_name: "Claude Code" });
    vi.mocked(apiClient.post).mockResolvedValue({ redirect_to: "http://cb" });
    const { result } = renderHook(() => useConsentRequest("r1"), { wrapper });
    await waitFor(() => expect(result.current.request).not.toBeNull());

    await act(() => result.current.approve.mutateAsync(["agents:view"]));
    await act(() => result.current.deny.mutateAsync());

    expect(apiClient.get).toHaveBeenCalledWith("/mcp-oauth/requests/r1");
    expect(apiClient.post).toHaveBeenCalledWith("/mcp-oauth/requests/r1/approve", {
      scopes: ["agents:view"],
    });
    expect(apiClient.post).toHaveBeenCalledWith("/mcp-oauth/requests/r1/deny");
  });
});

describe("useConnectedApps", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists, disconnects, and says so either way", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useConnectedApps(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(() => result.current.disconnect.mutateAsync("g1"));
    expect(apiClient.delete).toHaveBeenCalledWith("/mcp-oauth/grants/g1");
    expect(toastSuccess).toHaveBeenCalledWith("Application disconnected");

    vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("gone"));
    await act(async () => {
      await result.current.disconnect.mutateAsync("g2").catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
    expect(result.current.apps).toEqual([]);
  });
});
