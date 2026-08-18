import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useModelProviders, useProviderModels } from "./use-model-providers";
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

  it("surfaces a refused removal instead of leaving the row in place silently", async () => {
    // The server refuses deleting a profile an agent still points at, and the
    // panel's only way to say so is the toast.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("A published agent uses this model"));
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.deleteProfile.mutateAsync("p1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("A published agent uses this model");
  });

  it("does not call an empty list of models the organization's answer when the read failed", async () => {
    // `profiles` degrades to `[]` either way, so a caller reading it as "this
    // organization has no model" would say that about a 502. `profilesStatus`
    // is the difference, and only the successful read carries `loaded`.
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles"
        ? Promise.reject(new Error("upstream timed out"))
        : Promise.resolve({ items: [], total: 0 }),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.profiles).toEqual([]);
    expect(result.current.profilesStatus).toBe("failed");
  });

  it("separates a read still in flight from one that failed", async () => {
    // The third state, and the one a pair of booleans loses: a cold render is
    // `[]` too, and a caller that only knew "not loaded" would raise a failure
    // on the ordinary path - every first paint of the Builder.
    let answer: (value: { items: []; total: number }) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles"
        ? new Promise((resolve) => {
            answer = resolve;
          })
        : Promise.resolve({ items: [], total: 0 }),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });

    expect(result.current.profiles).toEqual([]);
    expect(result.current.profilesStatus).toBe("pending");

    answer({ items: [], total: 0 });
    await waitFor(() => expect(result.current.profilesStatus).toBe("loaded"));
  });

  it("calls an empty list the organization's answer when the read succeeded", async () => {
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.profilesStatus).toBe("loaded"));

    expect(result.current.profiles).toEqual([]);
  });

  it("removes a model", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.deleteProfile.mutateAsync("p1");
    expect(apiClient.delete).toHaveBeenCalledWith("/providers/model-profiles/p1");
  });
});

/**
 * The dropdown behind the model-id field.
 *
 * Suggestions, never a constraint: a provider ships a model the morning after
 * this list was cached, so the field stays free text and an unreachable provider
 * has to degrade to an empty list rather than to an error.
 */
describe("useProviderModels", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the models one provider offers", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "gpt-5", name: "GPT-5", context_length: 400_000 }],
      total: 1,
      source: "live",
    });

    const { result } = renderHook(() => useProviderModels("openai"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/providers/openai/models");
    expect(result.current.models).toHaveLength(1);
    expect(result.current.source).toBe("live");
  });

  it("says the list is this deployment's own when the provider published none", () => {
    // The field's helper text differs: a curated list is worth saying out loud,
    // because a model missing from it is not a model that does not exist.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, source: "curated" });

    const { result } = renderHook(() => useProviderModels("ollama"), { wrapper });

    return waitFor(() => expect(result.current.source).toBe("curated"));
  });

  it("does not fetch before a provider is chosen", () => {
    renderHook(() => useProviderModels(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("degrades to an empty list when the provider cannot be reached", async () => {
    // An empty dropdown is the state the field is built for; an error would put a
    // failure banner over a form that works perfectly well without suggestions.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("upstream timed out"));

    const { result } = renderHook(() => useProviderModels("openai"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.models).toEqual([]);
    expect(result.current.source).toBeNull();
  });
});
