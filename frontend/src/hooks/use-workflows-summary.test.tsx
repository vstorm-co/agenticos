import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/lib/workflows/workflows-api";
import type { WorkflowApprovalsSummary, WorkflowsSummary } from "@/lib/workflows/types";

import { useWorkflowApprovalsSummary, useWorkflowsSummary } from "./use-workflows-summary";

vi.mock("@/lib/workflows/workflows-api", () => ({
  getWorkflowsSummary: vi.fn(),
  getWorkflowApprovalsSummary: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useWorkflowsSummary", () => {
  it("reads the summary for the days given, and none until it arrives", async () => {
    vi.mocked(api.getWorkflowsSummary).mockResolvedValue({ runs: 4 } as WorkflowsSummary);
    const { result } = renderHook(() => useWorkflowsSummary("2026-10-01", "2026-10-07"), {
      wrapper,
    });

    expect(result.current.summary).toBeNull();
    await waitFor(() => expect(result.current.summary?.runs).toBe(4));
    expect(api.getWorkflowsSummary).toHaveBeenCalledWith("2026-10-01", "2026-10-07");
  });
});

describe("useWorkflowApprovalsSummary", () => {
  it("reads the approval outcomes for the days given, and none until they arrive", async () => {
    vi.mocked(api.getWorkflowApprovalsSummary).mockResolvedValue({
      requests: 6,
    } as WorkflowApprovalsSummary);
    const { result } = renderHook(() => useWorkflowApprovalsSummary("2026-10-01", "2026-10-07"), {
      wrapper,
    });

    expect(result.current.summary).toBeNull();
    await waitFor(() => expect(result.current.summary?.requests).toBe(6));
    expect(api.getWorkflowApprovalsSummary).toHaveBeenCalledWith("2026-10-01", "2026-10-07");
  });
});
