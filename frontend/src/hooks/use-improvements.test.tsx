import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useImprovement, useImprovements } from "./use-improvements";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
});
it("estimates without writing, starts with the confirmed limit and loads durable sessions", async () => {
  vi.mocked(apiClient.get).mockResolvedValue([{ id: "s1", status: "published" }]);
  vi.mocked(apiClient.post).mockResolvedValue({ id: "s2" });
  const { result } = renderHook(() => useImprovements("a1"), { wrapper });
  await waitFor(() => expect(result.current.sessions).toHaveLength(1));
  const invalidation = vi.spyOn(client, "invalidateQueries");
  await result.current.estimate.mutateAsync({ dataset_id: "d1", max_iterations: 3 });
  expect(invalidation).not.toHaveBeenCalled();
  await result.current.start.mutateAsync({ dataset_id: "d1", budget_usd: "0.50" });
  expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/improvements", {
    dataset_id: "d1",
    budget_usd: "0.50",
  });
  expect(invalidation).toHaveBeenCalledWith({ queryKey: ["improvements"] });
});
it("does not read a hidden session listing", () => {
  renderHook(() => useImprovements("a1", { enabled: false }), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});
it("loads a reopened session and requires the reviewed price for attribution", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "s1", status: "ready" });
  vi.mocked(apiClient.post).mockResolvedValue({});
  const { result } = renderHook(() => useImprovement("a1", "s1"), { wrapper });
  await waitFor(() => expect(result.current.session?.id).toBe("s1"));
  await result.current.estimateAttribution.mutateAsync(2);
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/rounds/2/attribution/estimate",
    {},
  );
  await result.current.attribute.mutateAsync({ number: 2, estimate: "0.02" });
  expect(apiClient.post).toHaveBeenLastCalledWith(
    "/agents/a1/improvements/s1/rounds/2/attribution",
    { confirmed: true, estimate_usd: "0.02" },
  );
  await result.current.selectRound.mutateAsync(1);
  await result.current.retry.mutateAsync();
  await result.current.cancel.mutateAsync();
  await result.current.finish.mutateAsync({
    confirmed: true,
    publish: true,
    automatic_check: true,
  });
  expect(apiClient.post).toHaveBeenLastCalledWith("/agents/a1/improvements/s1/finish", {
    confirmed: true,
    publish: true,
    automatic_check: true,
  });
});
