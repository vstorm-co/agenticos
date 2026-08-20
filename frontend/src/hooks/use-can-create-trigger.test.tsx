import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCanCreateTrigger } from "./use-can-create-trigger";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

type Page = { items: Array<{ id: string; can_run: boolean }>; total: number };

function serve(...pages: Page[]) {
  let call = 0;
  vi.mocked(apiClient.get).mockImplementation(() => Promise.resolve(pages[call++]));
}

describe("useCanCreateTrigger", () => {
  beforeEach(() => vi.clearAllMocks());

  it("is true when at least one agent is runnable", async () => {
    // The floor is per-agent, not the role: one runnable agent - by role or by a
    // run grant on it - is enough to offer the org-wide create controls.
    serve({
      items: [
        { id: "a1", can_run: false },
        { id: "a2", can_run: true },
      ],
      total: 2,
    });
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    await waitFor(() => expect(result.current).toBe(true));
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("keeps paging until the one runnable agent past the first page is found", async () => {
    // A Viewer holding a run grant on one old agent behind a hundred newer ones
    // must still see the create controls - the first page alone says false.
    const filler = Array.from({ length: 100 }, (_, i) => ({ id: `a${i}`, can_run: false }));
    serve({ items: filler, total: 101 }, { items: [{ id: "granted", can_run: true }], total: 101 });
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    await waitFor(() => expect(result.current).toBe(true));
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("is false when no agent on any page is runnable", async () => {
    const filler = Array.from({ length: 100 }, (_, i) => ({ id: `a${i}`, can_run: false }));
    serve({ items: filler, total: 101 }, { items: [{ id: "last", can_run: false }], total: 101 });
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    // It resolves - every page answered - and the answer is false.
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(result.current).toBe(false);
  });

  it("stops on an empty page rather than trusting a stale total", async () => {
    // An agent deleted mid-sweep can leave `total` promising a page that comes
    // back empty; that ends the sweep instead of spinning it.
    serve({ items: [], total: 5 });
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    expect(result.current).toBe(false);
  });

  it("is false while the list is still loading", () => {
    // The same conservatism `usePermissions` applies: reveal the control once the
    // data says it may be, rather than flash it and withdraw it.
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    expect(result.current).toBe(false);
  });
});
