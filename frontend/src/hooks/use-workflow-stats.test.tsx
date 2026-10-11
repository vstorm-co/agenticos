import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/lib/workflows/workflows-api";
import type { WorkflowStats } from "@/lib/workflows/types";

import { useWorkflowStats } from "./use-workflow-stats";

vi.mock("@/lib/workflows/workflows-api", () => ({ getWorkflowStats: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useWorkflowStats", () => {
  it("reads the workflow's figures for the window, and none until they arrive", async () => {
    vi.mocked(api.getWorkflowStats).mockResolvedValue({ runs: 3 } as WorkflowStats);
    const { result } = renderHook(() => useWorkflowStats("wf", 30), { wrapper });

    expect(result.current.stats).toBeNull();
    await waitFor(() => expect(result.current.stats?.runs).toBe(3));
    expect(api.getWorkflowStats).toHaveBeenCalledWith("wf", 30);
  });
});
