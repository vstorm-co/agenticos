import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { providerInfo, useModelProviders } from "./use-model-providers";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useModelProviders", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("creates a model against a chosen key", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ label: "Claude (prod)" });
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createProfile.mutateAsync({
      label: "Claude (prod)",
      provider: "anthropic",
      model: "claude-sonnet-4-6",
      secret_id: "s1",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/providers/model-profiles",
      expect.objectContaining({ model: "claude-sonnet-4-6", secret_id: "s1" }),
    );
  });

  it("removes a model", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.deleteProfile.mutateAsync("p1");
    expect(apiClient.delete).toHaveBeenCalledWith("/providers/model-profiles/p1");
  });
});

describe("providerInfo", () => {
  const catalog = [
    {
      id: "ollama",
      name: "Ollama",
      secret_kind: "api_key" as const,
      supports_base_url: true,
      keyless: true,
    },
  ];

  it("finds the entry a form branches on", () => {
    expect(providerInfo(catalog, "ollama")?.keyless).toBe(true);
  });

  it("returns null for a provider this deployment does not offer", () => {
    // A credential stored before a provider was removed still has to render.
    // Guessing a shape for it would open a form nobody can save.
    expect(providerInfo(catalog, "retired")).toBeNull();
  });
});
