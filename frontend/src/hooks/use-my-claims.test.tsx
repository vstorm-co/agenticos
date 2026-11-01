import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMyClaims } from "./use-my-claims";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org-1" }),
}));

const PAGE = { items: [], total: 0 };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(PAGE);
  vi.mocked(apiClient.post).mockResolvedValue({});
});

describe("useMyClaims", () => {
  it("reads the live claims, and the history when asked", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper });
    await waitFor(() => expect(result.current.page).toEqual(PAGE));
    expect(apiClient.get).toHaveBeenCalledWith("/memory/claims/mine?limit=100&history=false");

    act(() => result.current.setHistory(true));

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/memory/claims/mine?limit=100&history=true"),
    );
  });

  it("posts a correction and a retraction", async () => {
    const { result } = renderHook(() => useMyClaims(), { wrapper });
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

  it("reports a failed correction rather than swallowing it", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useMyClaims(), { wrapper });
    await waitFor(() => expect(result.current.page).toBeDefined());

    await act(() => result.current.correct("c-1", "New", null));
    await act(() => result.current.retract("c-1"));

    await waitFor(() => expect(toastError).toHaveBeenCalledTimes(2));
  });
});
