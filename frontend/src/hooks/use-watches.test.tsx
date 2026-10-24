import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  listWatches: vi.fn(),
  listWatchPresets: vi.fn(),
  createWatch: vi.fn(),
  updateWatch: vi.fn(),
  deleteWatch: vi.fn(),
}));
vi.mock("@/lib/watches-api", () => api);

import { useWatchPresets, useWatches } from "./use-watches";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useWatches", () => {
  it("reads the person's watches and reads them again after every change", async () => {
    api.listWatches.mockResolvedValue([{ id: "w1" }]);
    api.createWatch.mockResolvedValue({ id: "w2" });
    api.updateWatch.mockResolvedValue({ id: "w1" });
    api.deleteWatch.mockResolvedValue(undefined);
    const { result } = renderHook(() => useWatches(), { wrapper });
    expect(result.current.watches).toEqual([]);

    await waitFor(() => expect(result.current.watches).toEqual([{ id: "w1" }]));
    const draft = {
      connection_id: "c1",
      preset_key: null,
      title: "t",
      instructions: "i",
      urgent: false,
      interval_minutes: 60,
    };
    await result.current.create(draft);
    await result.current.update({ id: "w1", changes: { urgent: true } });
    await result.current.remove("w1");

    await waitFor(() => expect(api.listWatches).toHaveBeenCalledTimes(4));
    expect(api.createWatch).toHaveBeenCalledWith(draft);
    expect(api.updateWatch).toHaveBeenCalledWith("w1", { urgent: true });
    expect(api.deleteWatch).toHaveBeenCalledWith("w1");
  });
});

describe("useWatchPresets", () => {
  it("is empty until the presets arrive", async () => {
    api.listWatchPresets.mockResolvedValue([{ key: "github-reviews" }]);
    const { result } = renderHook(() => useWatchPresets(), { wrapper });
    expect(result.current).toEqual([]);
    await waitFor(() => expect(result.current).toEqual([{ key: "github-reviews" }]));
  });
});

it("keeps a failed list distinguishable from an empty list and retries", async () => {
  const error = new Error("unavailable");
  api.listWatches.mockRejectedValueOnce(error).mockResolvedValue([]);
  const { result } = renderHook(() => useWatches(), { wrapper });
  await waitFor(() => expect(result.current.error).toBe(error));
  await act(async () => {
    await result.current.refetch();
  });
  await waitFor(() => expect(result.current.error).toBeNull());
});
