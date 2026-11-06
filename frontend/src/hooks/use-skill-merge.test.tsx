import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  useBehindMain,
  useReturnForkToMain,
  useReturnToMain,
  useSkillMerge,
  useSkillMergeStart,
} from "./use-skill-merge";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

it("prices a catch-up on the fork's own route and starts it with the limit", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "s1" });
  const { result } = renderHook(() => useSkillMergeStart("k1", "f1", "catch_up"), { wrapper });

  await act(() => result.current.estimate.mutateAsync());
  await act(() => result.current.start.mutateAsync("2"));

  expect(apiClient.post).toHaveBeenNthCalledWith(1, "/skills/k1/forks/f1/catch-up/estimate", {});
  expect(apiClient.post).toHaveBeenNthCalledWith(2, "/skills/k1/forks/f1/catch-up", {
    budget_usd: "2",
  });
});

it("moves a fork to main on its own route", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "s1" });
  const { result } = renderHook(() => useSkillMergeStart("k1", "f1", "to_main"), { wrapper });

  await act(() => result.current.start.mutateAsync("1"));

  expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/forks/f1/to-main", { budget_usd: "1" });
});

it("reads a session's merge and keeps each edit's answer as the merge", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "m1", unresolved: 2 });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "m1", unresolved: 1 });
  const { result } = renderHook(() => useSkillMerge("k1", "s1", { at: "waiting:filtering" }), {
    wrapper,
  });
  await waitFor(() => expect(result.current.merge).toEqual({ id: "m1", unresolved: 2 }));

  await act(() => result.current.editDescription.mutateAsync("Refunds."));
  await act(() => result.current.editPart.mutateAsync({ index: 3, result: "both" }));
  await act(() => result.current.pickFile.mutateAsync({ name: "a.md", take: "fork" }));

  const root = "/skills/k1/improvements/s1/merge";
  expect(apiClient.get).toHaveBeenCalledWith(root);
  expect(apiClient.patch).toHaveBeenNthCalledWith(1, `${root}/description`, {
    result: "Refunds.",
  });
  expect(apiClient.patch).toHaveBeenNthCalledWith(2, `${root}/parts/3`, { result: "both" });
  expect(apiClient.patch).toHaveBeenNthCalledWith(3, `${root}/files`, {
    name: "a.md",
    take: "fork",
  });
  await waitFor(() => expect(result.current.merge).toEqual({ id: "m1", unresolved: 1 }));
});

it("does not read a merge for a session that merges nothing", () => {
  renderHook(() => useSkillMerge("k1", "s1", { at: "running:proposing", enabled: false }), {
    wrapper,
  });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("returns a catch-up's agents to main with the session's consent", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ session: { id: "s1" }, returned: {} });
  const { result } = renderHook(() => useReturnToMain("k1", "s1"), { wrapper });

  await act(() => result.current.mutateAsync(true));

  expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/s1/return-to-main", {
    confirmed: true,
    acknowledge_unknown: true,
  });
});

it("reads what main left behind, and only for a card that is shown", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, hidden: 1 });
  const { result } = renderHook(() => useBehindMain(), { wrapper });
  await waitFor(() => expect(result.current.behind?.hidden).toBe(1));
  expect(apiClient.get).toHaveBeenCalledWith("/skills/behind-main");

  vi.mocked(apiClient.get).mockClear();
  renderHook(() => useBehindMain({ enabled: false }), { wrapper });
  expect(apiClient.get).not.toHaveBeenCalled();
});

it("returns a fork's agents to main from the skill page", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({
    agents: [],
    hidden: 0,
    remaining: 0,
    archived: true,
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useReturnForkToMain("k1", "f1"), { wrapper });

  await act(() => result.current.mutateAsync());

  expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/forks/f1/return-to-main", {});
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
});
