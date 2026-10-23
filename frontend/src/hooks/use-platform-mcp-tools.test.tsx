import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { usePlatformMcpTools } from "./use-mcp-servers";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("usePlatformMcpTools", () => {
  it("reads the platform server's tools once, for a binding to choose from", async () => {
    const tool = { name: "whoami", description: "Which organization.", writes: false };
    vi.mocked(apiClient.get).mockResolvedValue({ items: [tool], total: 1 });

    const { result } = renderHook(() => usePlatformMcpTools(), { wrapper });

    expect(result.current.tools).toEqual([]);
    await waitFor(() => expect(result.current.tools).toEqual([tool]));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/platform-mcp-tools");
  });
});
