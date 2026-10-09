import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useApiKeys } from "./use-api-keys";
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

describe("useApiKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/api-keys" ? { items: [], total: 0 } : { scopes: ["agents:view"], presets: [] },
    );
  });

  it("asks for the scope catalog only from somebody who may create a key", async () => {
    const { result } = renderHook(() => useApiKeys({ canCreate: false }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/api-keys");
    expect(apiClient.get).not.toHaveBeenCalledWith("/api-keys/scopes");
    expect(result.current.catalog).toBeNull();
    expect(result.current.keys).toEqual([]);
  });

  it("creates a key and hands the key itself back to the caller", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ key: "aos_0123abcdsecret" });
    const { result } = renderHook(() => useApiKeys({ canCreate: true }), { wrapper });
    await waitFor(() => expect(result.current.catalog).not.toBeNull());

    const created = await act(() =>
      result.current.create.mutateAsync({ name: "ci", scopes: ["agents:view"], expires_at: null }),
    );

    expect(created.key).toBe("aos_0123abcdsecret");
    expect(apiClient.post).toHaveBeenCalledWith("/api-keys", {
      name: "ci",
      scopes: ["agents:view"],
      expires_at: null,
    });
  });

  it("revokes, and says so either way", async () => {
    vi.mocked(apiClient.delete).mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useApiKeys({ canCreate: false }), { wrapper });

    await act(() => result.current.revoke.mutateAsync("k1"));
    expect(apiClient.delete).toHaveBeenCalledWith("/api-keys/k1");
    expect(toastSuccess).toHaveBeenCalledWith("Key revoked");

    vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("gone"));
    await act(async () => {
      await result.current.revoke.mutateAsync("k2").catch(() => undefined);
    });
    expect(toastError).toHaveBeenCalled();
  });
});
