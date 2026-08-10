import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardLayout } from "./use-dashboard-layout";
import * as api from "@/lib/dashboard-layout-api";
import { useOrgStore } from "@/stores";

vi.mock("@/lib/dashboard-layout-api", () => ({
  getLayout: vi.fn(),
  putLayout: vi.fn(),
  deleteLayout: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function hook() {
  const rendered = renderHook(() => useDashboardLayout(), { wrapper });
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered.result;
}

beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org1" });
});

describe("useDashboardLayout", () => {
  it("reports no arrangement when none is saved", async () => {
    vi.mocked(api.getLayout).mockResolvedValue(null);
    const result = await hook();
    expect(result.current.storedEntries).toBeNull();
  });

  it("exposes the saved arrangement's entries", async () => {
    vi.mocked(api.getLayout).mockResolvedValue({ entries: [{ widget: "runs", span: "s8" }] });
    const result = await hook();
    expect(result.current.storedEntries).toEqual([{ widget: "runs", span: "s8" }]);
  });

  it("writes the saved arrangement into the cache so the page re-renders without a refetch", async () => {
    vi.mocked(api.getLayout).mockResolvedValue(null);
    vi.mocked(api.putLayout).mockResolvedValue({ entries: [{ widget: "spend", span: "s6" }] });
    const result = await hook();

    await act(async () => {
      await result.current.save([{ widget: "spend", span: "s6" }]);
    });

    expect(api.putLayout).toHaveBeenCalledWith([{ widget: "spend", span: "s6" }]);
    await waitFor(() =>
      expect(result.current.storedEntries).toEqual([{ widget: "spend", span: "s6" }]),
    );
  });

  it("clears the arrangement on reset", async () => {
    vi.mocked(api.getLayout).mockResolvedValue({ entries: [{ widget: "runs", span: "s8" }] });
    vi.mocked(api.deleteLayout).mockResolvedValue();
    const result = await hook();

    await act(async () => {
      await result.current.reset();
    });

    expect(api.deleteLayout).toHaveBeenCalled();
    await waitFor(() => expect(result.current.storedEntries).toBeNull());
  });

  it("still resolves a layout when there is no active organization yet", async () => {
    useOrgStore.setState({ activeOrgId: null });
    vi.mocked(api.getLayout).mockResolvedValue(null);
    const result = await hook();
    expect(result.current.storedEntries).toBeNull();
  });
});
