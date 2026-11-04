import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/lib/workflows/recent-logs-api";

import { useRecentWorkflowLogs } from "./use-recent-workflow-logs";

vi.mock("@/lib/workflows/recent-logs-api", () => ({ getRecentWorkflowLogs: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRecentWorkflowLogs", () => {
  it("reads the newest lines, and none until they arrive", async () => {
    vi.mocked(api.getRecentWorkflowLogs).mockResolvedValue({
      items: [],
      counts: { out: 3 },
    });
    const { result } = renderHook(() => useRecentWorkflowLogs(8), { wrapper });

    expect(result.current.logs).toBeNull();
    await waitFor(() => expect(result.current.logs?.counts).toEqual({ out: 3 }));
    expect(api.getRecentWorkflowLogs).toHaveBeenCalledWith(8);
  });

  it("hands a failed read on as an error, not as a quiet log", async () => {
    vi.mocked(api.getRecentWorkflowLogs).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useRecentWorkflowLogs(8), { wrapper });

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.logs).toBeNull();
  });
});
