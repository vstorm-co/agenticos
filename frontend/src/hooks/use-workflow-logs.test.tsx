import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/lib/workflows/logs-api";
import type { LogQuery, WorkflowLogEntry } from "@/lib/workflows/types";

import { useWorkflowLogs } from "./use-workflow-logs";

vi.mock("@/lib/workflows/logs-api", () => ({ listWorkflowLogs: vi.fn() }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const QUERY: LogQuery = { workflowId: "wf", includeTest: false, page: 0 };

describe("useWorkflowLogs", () => {
  it("reads a page of the log, and none until it arrives", async () => {
    vi.mocked(api.listWorkflowLogs).mockResolvedValue({
      items: [{ id: "e1" } as WorkflowLogEntry],
      total: 7,
    });
    const { result } = renderHook(() => useWorkflowLogs(QUERY), { wrapper });

    expect(result.current.entries).toEqual([]);
    await waitFor(() => expect(result.current.total).toBe(7));
    expect(result.current.entries).toHaveLength(1);
    expect(api.listWorkflowLogs).toHaveBeenCalledWith(QUERY);
  });

  it("hands a failed read on as an error, not as an empty log", async () => {
    vi.mocked(api.listWorkflowLogs).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowLogs(QUERY), { wrapper });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.entries).toEqual([]);
  });
});
