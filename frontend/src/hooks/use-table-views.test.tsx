import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTableViews } from "./use-table-views";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
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

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useTableViews", () => {
  it("is disabled when no table id is given", () => {
    const { result } = renderHook(() => useTableViews(null), { wrapper });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.views).toEqual([]);
  });

  it("invalidating with no table id is a no-op, rather than a query key built from null", async () => {
    // `create` casts `tableId as string` to call the API, so nothing stops a
    // caller from invoking it before an id exists; this is what keeps its
    // `onSuccess` invalidation a no-op instead of a query key built from `null`.
    vi.mocked(apiClient.post).mockResolvedValue({ id: "v1", name: "Board", kind: "kanban" });
    const { result } = renderHook(() => useTableViews(null), { wrapper });

    result.current.create.mutate({ name: "Board", kind: "kanban" });

    await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("lists every view when no kind filter is given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        { id: "v1", kind: "table", name: "Grid" },
        { id: "v2", kind: "kanban", name: "Board" },
      ],
      total: 2,
    });
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.views).toHaveLength(2);
  });

  it("narrows to one kind client-side", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        { id: "v1", kind: "table", name: "Grid" },
        { id: "v2", kind: "kanban", name: "Board" },
      ],
      total: 2,
    });
    const { result } = renderHook(() => useTableViews("t1", "kanban"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.views).toEqual([{ id: "v2", kind: "kanban", name: "Board" }]);
  });

  it("creates a view and toasts on success, without an onError - the dialog shows a conflict", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "v1", name: "Board", kind: "kanban" });
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.create.mutate({ name: "Board", kind: "kanban" });

    await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("updates a view with no toast on success", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "v1", name: "Renamed", kind: "kanban" });
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.update.mutate({ viewId: "v1", data: { name: "Renamed" } });

    await waitFor(() => expect(result.current.update.isSuccess).toBe(true));
  });

  it("leaves a refused update to the rename dialog, which shows it - no toast", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(404, "View not found"));
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.update.mutate({ viewId: "v1", data: { name: "Renamed" } });

    await waitFor(() => expect(result.current.update.isError).toBe(true));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("deletes a view and toasts on success", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.remove.mutate("v1");

    await waitFor(() => expect(result.current.remove.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts a localized message when deleting a view is refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.delete).mockRejectedValue(new ApiError(404, "View not found"));
    const { result } = renderHook(() => useTableViews("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.remove.mutate("v1");

    await waitFor(() => expect(result.current.remove.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });
});
