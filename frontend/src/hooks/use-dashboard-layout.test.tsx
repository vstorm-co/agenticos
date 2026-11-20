import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboardLayout } from "./use-dashboard-layout";
import * as api from "@/lib/dashboard-layout-api";
import { ApiError } from "@/lib/api-client";
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

  it("treats an empty saved arrangement as [], distinct from no preference", async () => {
    // The page leans on this: [] is "hid every card", null is "use the default".
    // A truthy-object check keeps them apart, so a saved empty layout must not
    // collapse to null.
    vi.mocked(api.getLayout).mockResolvedValue({ entries: [] });
    const result = await hook();
    expect(result.current.storedEntries).toEqual([]);
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

  it("reports a failed read as a load error, not as no saved arrangement", async () => {
    // The page renders the audience default for `null`, so a 5xx must never land there.
    vi.mocked(api.getLayout).mockRejectedValue(new ApiError(503, "Service unavailable"));
    const result = await hook();
    expect(result.current.loadError).toBeInstanceOf(ApiError);
    expect(result.current.storedEntries).toBeNull();
  });

  it("reports a network failure as a load error too", async () => {
    vi.mocked(api.getLayout).mockRejectedValue(new TypeError("Failed to fetch"));
    const result = await hook();
    expect(result.current.loadError).toBeInstanceOf(TypeError);
    expect(result.current.storedEntries).toBeNull();
  });

  it("does not report a confirmed 404 (no saved layout) as a load error", async () => {
    vi.mocked(api.getLayout).mockResolvedValue(null);
    const result = await hook();
    expect(result.current.loadError).toBeNull();
    expect(result.current.storedEntries).toBeNull();
  });

  it("retries a failed read and exposes the saved arrangement once the retry succeeds", async () => {
    vi.mocked(api.getLayout)
      .mockRejectedValueOnce(new ApiError(503, "Service unavailable"))
      .mockResolvedValueOnce({ entries: [{ widget: "runs", span: "s8" }] });
    const result = await hook();
    expect(result.current.loadError).toBeInstanceOf(ApiError);

    await act(async () => {
      await result.current.retryLoad();
    });

    expect(api.getLayout).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(result.current.loadError).toBeNull());
    expect(result.current.storedEntries).toEqual([{ widget: "runs", span: "s8" }]);
  });

  it("keeps the arrangement already read when a later refresh fails", async () => {
    // Once a read has succeeded the arrangement is known; a failed refresh must not
    // hide it or turn it into the default.
    vi.mocked(api.getLayout)
      .mockResolvedValueOnce({ entries: [{ widget: "runs", span: "s8" }] })
      .mockRejectedValueOnce(new ApiError(500, "boom"));
    const result = await hook();

    await act(async () => {
      await result.current.retryLoad();
      // TanStack Query notifies observers on a timer; let the failed refresh reach the hook.
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(api.getLayout).toHaveBeenCalledTimes(2);
    expect(result.current.loadError).toBeNull();
    expect(result.current.storedEntries).toEqual([{ widget: "runs", span: "s8" }]);
  });
});
