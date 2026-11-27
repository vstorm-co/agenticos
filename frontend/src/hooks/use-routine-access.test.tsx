import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { routineAccessFixture } from "@/test-utils/routine-access";

const api = vi.hoisted(() => ({ get: vi.fn(), replace: vi.fn() }));
vi.mock("@/lib/routine-access-api", () => ({ routineAccessApi: api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

import { isStaleReview, useRoutineAccess, useRoutineAccessCheck } from "./use-routine-access";

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, Wrapper };
}

const update = {
  review_token: "old",
  mode: "reviewed" as const,
  tools: [],
  delegates: "ask" as const,
};

beforeEach(() => vi.clearAllMocks());

it("reads the review again after a stale save, without a toast the dialog already explains", async () => {
  const stale = new ApiError(409, "Review its access again.");
  api.get
    .mockResolvedValueOnce(routineAccessFixture({ review_token: "old" }))
    .mockResolvedValue(routineAccessFixture({ review_token: "new" }));
  api.replace.mockRejectedValue(stale);
  const { Wrapper } = setup();
  const { result } = renderHook(() => useRoutineAccess("agent", "routine"), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.data?.review_token).toBe("old"));
  await act(async () => {
    await expect(result.current.save.mutateAsync(update)).rejects.toBe(stale);
  });
  await waitFor(() => expect(result.current.data?.review_token).toBe("new"));
  expect(toast.error).not.toHaveBeenCalled();
  expect(isStaleReview(stale)).toBe(true);
  expect(isStaleReview(new ApiError(403, "No"))).toBe(false);
});

it("toasts any other refusal", async () => {
  api.get.mockResolvedValue(routineAccessFixture());
  api.replace.mockRejectedValue(new ApiError(403, "Needs approvals:decide"));
  const { Wrapper } = setup();
  const { result } = renderHook(() => useRoutineAccess("agent", "routine"), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  await act(async () => {
    await expect(result.current.save.mutateAsync(update)).rejects.toThrow();
  });
  expect(toast.error).toHaveBeenCalledWith("Needs approvals:decide");
});

it("keeps the saved review and refreshes the routines and their readiness", async () => {
  const saved = routineAccessFixture({ review_token: "saved" });
  // What the server answers after the save, too, when the invalidation reads it again.
  api.get.mockResolvedValueOnce(routineAccessFixture()).mockResolvedValue(saved);
  api.replace.mockResolvedValue(saved);
  const { client, Wrapper } = setup();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useRoutineAccess("agent", "routine"), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  await act(async () => {
    await result.current.save.mutateAsync(update);
  });
  expect(api.replace).toHaveBeenCalledWith("agent", "routine", update);
  expect(client.getQueryData(qk.triggers.access("agent", "routine"))).toEqual(saved);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.triggers.all() });
});

it("checks whether an edited routine's review is still current", async () => {
  const { Wrapper } = setup();
  const { result } = renderHook(() => useRoutineAccessCheck(), { wrapper: Wrapper });
  api.get.mockResolvedValueOnce(routineAccessFixture({ current: false }));
  expect(await result.current("agent", "routine")).toBe(true);
  api.get.mockResolvedValueOnce(routineAccessFixture());
  expect(await result.current("agent", "routine")).toBe(false);
  api.get.mockRejectedValueOnce(new Error("offline"));
  expect(await result.current("agent", "routine")).toBe(false);
});
