import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkflowTable, useWorkflowTables } from "./use-workflow-tables";
import * as api from "@/lib/workflows/tables-api";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/workflows/tables-api", () => ({
  listTables: vi.fn(),
  getTable: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe("useWorkflowTables", () => {
  it("asks for one large page and returns its items", async () => {
    vi.mocked(api.listTables).mockResolvedValue({ items: [{ id: "t1" }] as never, total: 1 });
    const { result } = renderHook(() => useWorkflowTables(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(api.listTables).toHaveBeenCalledWith({ limit: 100 });
    expect(result.current.tables).toEqual([{ id: "t1" }]);
    expect(result.current.total).toBe(1);
  });

  it("stays out of the network when disabled, reporting empty", async () => {
    const { result } = renderHook(() => useWorkflowTables(false), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.tables).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(api.listTables).not.toHaveBeenCalled();
  });

  it("surfaces a refusal rather than swallowing it into an empty list", async () => {
    vi.mocked(api.listTables).mockRejectedValue(new ApiError(403, "nope"));
    const { result } = renderHook(() => useWorkflowTables(), { wrapper });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError));
    expect(result.current.tables).toEqual([]);
  });
});

describe("useWorkflowTable", () => {
  it("fetches the table for a non-null id", async () => {
    vi.mocked(api.getTable).mockResolvedValue({ id: "t1", schema_version: 2 } as never);
    const { result } = renderHook(() => useWorkflowTable("t1"), { wrapper });
    await waitFor(() => expect(result.current.table).not.toBeNull());
    expect(api.getTable).toHaveBeenCalledWith("t1");
    expect(result.current.table).toEqual({ id: "t1", schema_version: 2 });
  });

  it("makes no request and reports null for a null id", async () => {
    const { result } = renderHook(() => useWorkflowTable(null), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.table).toBeNull();
    expect(api.getTable).not.toHaveBeenCalled();
  });
});
