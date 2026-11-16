import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { usePendingApprovals } from "./use-pending-approvals";

const state = vi.hoisted(() => ({
  allowed: true,
  permissions: { isLoaded: true, isLoading: false, error: null as Error | null },
  refetchPermissions: vi.fn(),
  get: vi.fn(),
  decidable: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: () => state.allowed,
    ...state.permissions,
    refetch: state.refetchPermissions,
  }),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: state.get } }));
vi.mock("@/lib/workflows/approvals-api", () => ({
  listDecidableWorkflowApprovals: state.decidable,
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client }, children);
}

beforeEach(() => {
  state.allowed = true;
  state.permissions = { isLoaded: true, isLoading: false, error: null };
  state.refetchPermissions.mockReset();
  state.get.mockReset().mockResolvedValue({ items: [{ id: "t1" }], total: 3 });
  state.decidable.mockReset().mockResolvedValue({ items: [{ id: "s1" }], total: 60 });
});

it("counts what the server says waits on the reader, past the rows it lists", async () => {
  const { result } = renderHook(() => usePendingApprovals(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));

  expect(result.current.count).toBe(3 + 60);
  expect(result.current.tools.map((call) => call.id)).toEqual(["t1"]);
  expect(result.current.steps.map((step) => step.id)).toEqual(["s1"]);
  expect(state.get).toHaveBeenCalledWith("/approvals", {
    params: { outside_live_calls: "true", limit: "5" },
  });
  expect(state.decidable).toHaveBeenCalledWith(5);
});

it("asks neither queue for somebody who may not decide, and waits on nothing", async () => {
  state.allowed = false;
  const { result } = renderHook(() => usePendingApprovals(), { wrapper });
  expect(result.current).toMatchObject({
    tools: [],
    steps: [],
    count: 0,
    isLoading: false,
    error: null,
  });
  await result.current.refetch();
  expect(state.get).not.toHaveBeenCalled();
  expect(state.decidable).not.toHaveBeenCalled();
  expect(state.refetchPermissions).not.toHaveBeenCalled();
});

it("knows nothing while the reader's permissions load, and says so", () => {
  state.allowed = false;
  state.permissions = { isLoaded: false, isLoading: true, error: null };
  const { result } = renderHook(() => usePendingApprovals(), { wrapper });
  expect(result.current).toMatchObject({ count: 0, isLoading: true });
});

it("reports permissions that failed to load, and reads them again on a retry", async () => {
  const refused = new Error("offline");
  state.allowed = false;
  state.permissions = { isLoaded: false, isLoading: false, error: refused };
  const { result } = renderHook(() => usePendingApprovals(), { wrapper });
  expect(result.current.error).toBe(refused);
  await result.current.refetch();
  expect(state.refetchPermissions).toHaveBeenCalledOnce();
  expect(state.get).not.toHaveBeenCalled();
});

it("reports a queue that failed to load, and reads both again on a retry", async () => {
  const failed = new Error("offline");
  state.decidable.mockRejectedValue(failed);
  const { result } = renderHook(() => usePendingApprovals(), { wrapper });
  await waitFor(() => expect(result.current.error).toBe(failed));

  await result.current.refetch();
  expect(state.get).toHaveBeenCalledTimes(2);
  expect(state.decidable).toHaveBeenCalledTimes(2);
});
