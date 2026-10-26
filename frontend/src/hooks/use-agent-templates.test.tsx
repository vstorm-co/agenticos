import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useAgentTemplates } from "./use-agent-templates";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("useAgentTemplates", () => {
  it("recounts the agent ceiling after a refused install", async () => {
    // A refused install may be the agent limit the cached ceiling did not know.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("at the limit"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.agents.ceiling(), { limit: 5, held: 4 });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useAgentTemplates(false), { wrapper });

    result.current.install("support");

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("at the limit"));
    expect(client.getQueryState(qk.agents.ceiling())?.isInvalidated).toBe(true);
  });
});
