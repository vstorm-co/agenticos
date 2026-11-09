import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useMyClaims } from "./use-my-claims";
import { apiClient } from "@/lib/api-client";
import type { MemoryClaimFilters } from "@/lib/memory-api";
import { useOrgStore } from "@/stores";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-1" });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 250 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "c-1" });
});
it("resets pagination when the search, type or organization changes", async () => {
  const { result, rerender } = renderHook(
    ({ filters }: { filters: MemoryClaimFilters }) => useMyClaims(filters),
    { wrapper: Wrapper, initialProps: { filters: {} } },
  );
  await waitFor(() => expect(result.current.page).toBeDefined());
  act(() => result.current.showPage(100));
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=100&history=false",
    ),
  );
  rerender({ filters: { q: "invoice", kind: "decision" } });
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=0&history=false&q=invoice&kind=decision",
    ),
  );
  expect(result.current.skip).toBe(0);
  act(() => result.current.showPage(100));
  act(() => useOrgStore.setState({ activeOrgId: "org-2" }));
  await waitFor(() => expect(result.current.skip).toBe(0));
});
it("shows history from its first page and retains the selected scope", async () => {
  const { result } = renderHook(() => useMyClaims({ scope: "profile" }), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.page).toBeDefined());
  act(() => result.current.showPage(100));
  act(() => result.current.setHistory(true));
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=0&history=true&scope=profile",
    ),
  );
});
it("reports a refused correction or retraction without claiming success", async () => {
  const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.page).toBeDefined());
  vi.mocked(apiClient.post).mockRejectedValue(new Error("refused"));
  await act(async () => {
    expect(await result.current.correct("c-1", "Corrected", null)).toBe(false);
    expect(await result.current.retract("c-1")).toBe(false);
  });
});
it("waits for accepted changes and refreshes the memory store", async () => {
  const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.page).toBeDefined());
  vi.mocked(apiClient.get).mockClear();
  await act(async () => {
    expect(await result.current.correct("c-1", "Corrected", null)).toBe(true);
    expect(await result.current.retract("c-1")).toBe(true);
  });
  expect(apiClient.get).toHaveBeenCalled();
});

const PAGE = { items: [], total: 250 };

describe("useMyClaims", () => {
  it("reads the live claims, and the history when asked", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.page).toEqual(PAGE));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/memory/claims/mine?limit=100&skip=0&history=false",
    );

    act(() => result.current.setHistory(true));

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/memory/claims/mine?limit=100&skip=0&history=true",
      ),
    );
  });

  it("posts a correction and a retraction", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());

    await act(() => result.current.correct("c-1", "New", "2026-11-03T00:00:00Z"));
    await act(() => result.current.retract("c-2"));

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/c-1/correct", {
        statement: "New",
        effective_from: "2026-11-03T00:00:00Z",
      });
      expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/c-2/retract", {});
    });
  });

  it("says whether a correction was saved, and reports a refused one", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());
    let saved = false;
    await act(async () => {
      saved = await result.current.correct("c-1", "New", null);
    });
    expect(saved).toBe(true);

    vi.mocked(apiClient.post).mockRejectedValue(new Error("nope"));
    let refused = true;
    await act(async () => {
      refused = await result.current.correct("c-1", "New", null);
    });
    expect(refused).toBe(false);
    await act(() => result.current.retract("c-1"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
  });

  it("pages, and starts a different list from its first page", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());

    act(() => result.current.showPage(100));
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/memory/claims/mine?limit=100&skip=100&history=false",
      ),
    );
    act(() => result.current.setHistory(true));

    await waitFor(() => expect(result.current.skip).toBe(0));
  });
});

it("keeps the explicit decision evidence on a correction and supports the pre-organization cache scope", async () => {
  useOrgStore.setState({ activeOrgId: null });
  const { result } = renderHook(() => useMyClaims(), { wrapper: Wrapper });
  await waitFor(() => expect(result.current.page).toBeDefined());
  const episode = {
    situation: "Supplier late",
    choice: "Ask for date",
    alternatives: [],
    expected_outcome: null,
    actual_outcome: "Date confirmed",
    correction: "Ask earlier",
  };
  await act(async () => {
    expect(await result.current.correct("decision", "Ask earlier", null, episode)).toBe(true);
  });
  expect(apiClient.post).toHaveBeenCalledWith("/memory/claims/mine/decision/correct", {
    statement: "Ask earlier",
    effective_from: null,
    episode,
  });
  await act(async () => {
    expect(await result.current.retract("decision")).toBe(true);
  });
});
