import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardPresets } from "./use-dashboard-presets";
import * as api from "@/lib/dashboard-preset-api";
import { useOrgStore } from "@/stores";

vi.mock("@/lib/dashboard-preset-api", () => ({
  listPresets: vi.fn(),
  createPreset: vi.fn(),
  deletePreset: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function hook() {
  const rendered = renderHook(() => useDashboardPresets(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org1" });
});

describe("useDashboardPresets", () => {
  it("exposes the caller's presets", async () => {
    vi.mocked(api.listPresets).mockResolvedValue([
      { id: "p1", name: "Monday review", entries: [] },
    ]);
    const result = await hook();
    expect(result.current.presets).toEqual([{ id: "p1", name: "Monday review", entries: [] }]);
  });

  it("reports an empty shelf as an empty list, never undefined", async () => {
    vi.mocked(api.listPresets).mockResolvedValue([]);
    const result = await hook();
    expect(result.current.presets).toEqual([]);
  });

  it("refetches after saving so the server's list is what shows", async () => {
    vi.mocked(api.listPresets).mockResolvedValueOnce([]);
    vi.mocked(api.createPreset).mockResolvedValue({ id: "p1", name: "Monday review", entries: [] });
    vi.mocked(api.listPresets).mockResolvedValue([
      { id: "p1", name: "Monday review", entries: [] },
    ]);
    const result = await hook();

    await act(async () => {
      await result.current.savePreset("Monday review", [
        { widget: "runs", span: "s8", rows: "r3" },
      ]);
    });

    expect(api.createPreset).toHaveBeenCalledWith("Monday review", [
      { widget: "runs", span: "s8", rows: "r3" },
    ]);
    await waitFor(() =>
      expect(result.current.presets).toEqual([{ id: "p1", name: "Monday review", entries: [] }]),
    );
  });

  it("refetches after deleting", async () => {
    vi.mocked(api.listPresets).mockResolvedValueOnce([
      { id: "p1", name: "Monday review", entries: [] },
    ]);
    vi.mocked(api.deletePreset).mockResolvedValue();
    vi.mocked(api.listPresets).mockResolvedValue([]);
    const result = await hook();

    await act(async () => {
      await result.current.removePreset("p1");
    });

    expect(api.deletePreset).toHaveBeenCalledWith("p1");
    await waitFor(() => expect(result.current.presets).toEqual([]));
  });

  it("keys the query per organization, and resolves with none active yet", async () => {
    useOrgStore.setState({ activeOrgId: null });
    vi.mocked(api.listPresets).mockResolvedValue([]);
    const result = await hook();
    expect(result.current.presets).toEqual([]);
  });
});
