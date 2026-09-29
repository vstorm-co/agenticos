import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTableTriggerAdmissions, useTableTriggers } from "./use-table-triggers";
import { apiClient } from "@/lib/api-client";

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

describe("useTableTriggers", () => {
  it("lists a table's triggers and refreshes after each write", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "t1" }] });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "t2" });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "t1" });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useTableTriggers("tbl"), { wrapper });

    await waitFor(() => expect(result.current.triggers).toEqual([{ id: "t1" }]));
    result.current.create.mutate({ workflow_id: "wf" });
    await waitFor(() => expect(result.current.create.isSuccess).toBe(true));
    result.current.update.mutate({ id: "t1", body: { is_active: false } });
    await waitFor(() => expect(result.current.update.isSuccess).toBe(true));
    result.current.remove.mutate("t1");
    await waitFor(() => expect(result.current.remove.isSuccess).toBe(true));

    expect(toastSuccess).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(4));
  });

  it("says why a write was refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [] });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useTableTriggers("tbl"), { wrapper });

    expect(result.current.triggers).toEqual([]);
    result.current.create.mutate({ workflow_id: "wf" });

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});

describe("useTableTriggerAdmissions", () => {
  it("reads one trigger's history, empty until it arrives", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "a1" }], total: 1 });
    const { result } = renderHook(() => useTableTriggerAdmissions("tbl", "t1"), { wrapper });

    expect(result.current).toMatchObject({ admissions: [], total: 0 });
    await waitFor(() => expect(result.current.total).toBe(1));
    expect(result.current.admissions).toEqual([{ id: "a1" }]);
  });
});
