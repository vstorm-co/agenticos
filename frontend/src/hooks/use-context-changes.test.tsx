import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { contextChange } from "@/test-utils/authoring";

import { useContextChanges } from "./use-context-changes";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [contextChange()], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue(contextChange({ status: "applied" }));
});

describe("useContextChanges", () => {
  it("asks for the pending ones by default", async () => {
    const { result } = renderHook(() => useContextChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/context-changes", {
      params: { status: "pending" },
    });
  });

  it("applying reads the context files again, because every bound agent reads the new body", async () => {
    const { toast } = await import("sonner");
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useContextChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    act(() => result.current.apply(contextChange({ revision: 3 })));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Applied the change to house-style"),
    );
    expect(apiClient.post).toHaveBeenCalledWith("/context-changes/change-1/apply", {
      revision: 3,
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.context.all() });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.authoring.waiting() });
  });

  it("discards through its own route", async () => {
    const { toast } = await import("sonner");
    const { result } = renderHook(() => useContextChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    act(() => result.current.discard(contextChange({ revision: 3 })));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Discarded the change to house-style"),
    );
    expect(apiClient.post).toHaveBeenCalledWith("/context-changes/change-1/discard", {
      revision: 3,
    });
  });

  it("reports a refused decision and reads the changes again", async () => {
    // A file edited since the proposal answers 409; the row must turn stale,
    // not keep offering Apply.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValue(new Error("The file changed since."));
    const { result } = renderHook(() => useContextChanges(), { wrapper });
    await waitFor(() => expect(result.current.changes).toHaveLength(1));

    act(() => result.current.apply(contextChange({ revision: 3 })));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("The file changed since."));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));

    act(() => result.current.discard(contextChange({ revision: 3 })));
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
  });

  it("asks for nothing while it is not enabled", () => {
    const { result } = renderHook(() => useContextChanges("pending", { enabled: false }), {
      wrapper,
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.changes).toEqual([]);
  });

  it("says why the list is empty when the request failed", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("403 Forbidden"));
    const { result } = renderHook(() => useContextChanges("applied"), { wrapper });
    await waitFor(() => expect(result.current.error).toBe("403 Forbidden"));
    expect(result.current.changes).toEqual([]);
  });
});
