import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useMentionables } from "./use-mentionables";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useMentionables", () => {
  it("reads what the agent offers once the menu is wanted", async () => {
    const item = { kind: "skill", id: "s", name: "refunds" };
    vi.mocked(apiClient.get).mockResolvedValue({ items: [item], total: 1 });

    const { result, rerender } = renderHook(({ on }) => useMentionables("a-1", on), {
      wrapper,
      initialProps: { on: false },
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.items).toEqual([]);

    rerender({ on: true });
    await waitFor(() => expect(result.current.items).toEqual([item]));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a-1/mentionables");
  });

  it("asks nothing without an agent", () => {
    vi.mocked(apiClient.get).mockClear();
    renderHook(() => useMentionables(null, true), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
