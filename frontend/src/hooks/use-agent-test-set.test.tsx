import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useAgentTestSet } from "./use-agent-test-set";

vi.mock("@/lib/api-client", () => ({ apiClient: { post: vi.fn() } }));

const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useAgentTestSet", () => {
  it("estimates and builds the agent's test set, then refreshes the datasets", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({});
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useAgentTestSet("a1"), { wrapper });

    await result.current.estimate.mutateAsync({ more: 5 });
    expect(invalidate).not.toHaveBeenCalled();
    await result.current.build.mutateAsync({ since: "2026-10-01T00:00:00Z" });

    expect(vi.mocked(apiClient.post).mock.calls).toEqual([
      ["/agents/a1/test-set/estimate", { more: 5 }],
      ["/agents/a1/test-set", { since: "2026-10-01T00:00:00Z" }],
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["datasets"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agents"] });
  });
});
