import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTable, useTables } from "./use-tables";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
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

describe("useTables", () => {
  it("lists the catalog page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "t1", name: "Orders" }],
      total: 1,
    });
    const { result } = renderHook(() => useTables(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.tables[0]?.name).toBe("Orders");
    expect(result.current.total).toBe(1);
  });

  it("creates a table and invalidates the list on success", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "t1", name: "Orders" });
    const { result } = renderHook(() => useTables(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.create.mutate({ name: "Orders" });

    await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
    // Create sets no onError - a taken name is shown in the dialog itself.
    expect(toastError).not.toHaveBeenCalled();
  });

  it("archives a table and toasts on success", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "t1", archived_at: "2026-09-23" });
    const { result } = renderHook(() => useTables(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.archive.mutate("t1");

    await waitFor(() => expect(result.current.archive.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts a localized message when archiving fails", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(404, "Table not found"));
    const { result } = renderHook(() => useTables(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.archive.mutate("missing");

    await waitFor(() => expect(result.current.archive.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });
});

describe("useTable", () => {
  it("is disabled when no id is given", () => {
    const { result } = renderHook(() => useTable(null), { wrapper });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.table).toBeUndefined();
  });

  it("invalidating with no id is a no-op, rather than a query key built from null", async () => {
    // `update` and `changeSchema` cast `tableId as string` to call the API, so
    // nothing stops a caller from invoking them (or `invalidate` itself)
    // before an id exists; this is what keeps that a no-op instead of a query
    // key built from `null`.
    const { result } = renderHook(() => useTable(null), { wrapper });

    await result.current.invalidate();

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads one table by id", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "t1", name: "Orders", columns: [] });
    const { result } = renderHook(() => useTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.table?.name).toBe("Orders");
  });

  it("updates a table and toasts on success", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "t1", name: "Orders", columns: [] });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "t1", name: "Renamed", columns: [] });
    const { result } = renderHook(() => useTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.update.mutate({ name: "Renamed" });

    await waitFor(() => expect(result.current.update.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("toasts a localized message when the update is refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "t1", name: "Orders", columns: [] });
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(409, "Name taken"));
    const { result } = renderHook(() => useTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.update.mutate({ name: "Taken" });

    await waitFor(() => expect(result.current.update.isError).toBe(true));
    expect(toastError).toHaveBeenCalled();
  });

  it("changes the schema and invalidates schema versions on success, without a toast on failure path skipped", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "t1",
      name: "Orders",
      columns: [],
      schema_version: 1,
    });
    vi.mocked(apiClient.put).mockResolvedValue({
      id: "t1",
      name: "Orders",
      columns: [],
      schema_version: 2,
    });
    const { result } = renderHook(() => useTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.changeSchema.mutate({ expected_version: 1, columns: [] });

    await waitFor(() => expect(result.current.changeSchema.isSuccess).toBe(true));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("does not toast a schema-change failure - the dialog shows it inline", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      id: "t1",
      name: "Orders",
      columns: [],
      schema_version: 1,
    });
    vi.mocked(apiClient.put).mockRejectedValue(new ApiError(422, "Invalid schema"));
    const { result } = renderHook(() => useTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.changeSchema.mutate({ expected_version: 1, columns: [] });

    await waitFor(() => expect(result.current.changeSchema.isError).toBe(true));
    expect(toastError).not.toHaveBeenCalled();
  });
});
