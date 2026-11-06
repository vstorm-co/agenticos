import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import type { RoutineSourceReview } from "@/lib/routine-sources-api";

const api = vi.hoisted(() => ({ get: vi.fn(), replace: vi.fn() }));
vi.mock("@/lib/routine-sources-api", () => ({ routineSourcesApi: api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

import { useRoutineSources } from "./use-routine-sources";

it("refreshes a rejected review before a person can submit another consent", async () => {
  const initial: RoutineSourceReview = {
    current: false,
    review_token: "old",
    version_id: "v1",
    resources: [],
    accounts: [],
    unavailable_sources: [],
  };
  const current = { ...initial, review_token: "new" };
  const stale = new Error("The account changed. Review its actions again.");
  api.get.mockResolvedValueOnce(initial).mockResolvedValue(current);
  api.replace.mockRejectedValueOnce(stale).mockResolvedValue(current);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  const { result } = renderHook(() => useRoutineSources("agent", "routine"), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.data?.review_token).toBe("old"));
  await act(async () => {
    await expect(
      result.current.replace.mutateAsync(result.current.data!.review_token),
    ).rejects.toBe(stale);
  });
  await waitFor(() => expect(result.current.data?.review_token).toBe("new"));
  await act(async () => {
    await result.current.replace.mutateAsync(result.current.data!.review_token);
  });
  expect(api.replace).toHaveBeenNthCalledWith(1, "agent", "routine", "old");
  expect(api.replace).toHaveBeenNthCalledWith(2, "agent", "routine", "new");
  expect(api.get).toHaveBeenCalledTimes(3);
});
