import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import * as api from "@/lib/workflows/runs-api";
import type { WorkflowRunRead } from "@/lib/workflows/types";

import { useCausingRun, useRunHistory, useWorkflowRun, useWorkflowRuns } from "./use-workflow-runs";

vi.mock("@/lib/workflows/runs-api", () => ({
  listWorkflowRuns: vi.fn(),
  getWorkflowRun: vi.fn(),
  listWorkflowRunNodes: vi.fn(),
  getWorkflowRunGraph: vi.fn(),
  listWorkflowRunFiles: vi.fn(),
  startWorkflowRun: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  listRunHistory: vi.fn(),
  retryWorkflowRun: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function run(status: WorkflowRunRead["status"]): WorkflowRunRead {
  return { id: "r", status } as WorkflowRunRead;
}

beforeEach(() => vi.clearAllMocks());

describe("useWorkflowRuns", () => {
  it("lists a workflow's runs and starts one", async () => {
    vi.mocked(api.listWorkflowRuns).mockResolvedValue({ items: [run("running")], total: 1 });
    vi.mocked(api.startWorkflowRun).mockResolvedValue(run("queued"));
    const { result } = renderHook(() => useWorkflowRuns("wf"), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(1));
    await act(() => result.current.start.mutateAsync({ workflow_id: "wf" }));
    expect(toast.success).toHaveBeenCalledWith("Run started");
  });

  it("says why a run could not start", async () => {
    vi.mocked(api.listWorkflowRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.startWorkflowRun).mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useWorkflowRuns("wf"), { wrapper });
    await act(async () => {
      await result.current.start.mutateAsync({ workflow_id: "wf" }).catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.runs).toEqual([]);
  });
});

describe("useCausingRun", () => {
  it("reads the run that started this one, and nothing for a run nothing started", async () => {
    vi.mocked(api.getWorkflowRun).mockResolvedValue(run("succeeded"));
    const { result } = renderHook(() => useCausingRun("caller"), { wrapper });
    await waitFor(() => expect(result.current.causing).not.toBeNull());
    expect(api.getWorkflowRun).toHaveBeenCalledWith("caller");

    vi.mocked(api.getWorkflowRun).mockClear();
    const none = renderHook(() => useCausingRun(null), { wrapper });
    expect(none.result.current).toEqual({ causing: null, refused: false });
    expect(api.getWorkflowRun).not.toHaveBeenCalled();
  });

  it("says it is refused when the caller may not open that run", async () => {
    vi.mocked(api.getWorkflowRun).mockRejectedValue(new Error("Not found"));
    const { result } = renderHook(() => useCausingRun("hidden"), { wrapper });
    await waitFor(() => expect(result.current.refused).toBe(true));
    expect(result.current.causing).toBeNull();
  });
});

describe("useRunHistory", () => {
  it("reads a filtered page of runs", async () => {
    vi.mocked(api.listRunHistory).mockResolvedValue({ items: [run("succeeded")], total: 30 });
    const query = { status: "succeeded" as const, page: 1 };
    const { result } = renderHook(() => useRunHistory(query), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(30));
    expect(result.current.runs).toHaveLength(1);
    expect(api.listRunHistory).toHaveBeenCalledWith(query);
  });

  it("reads a live page again, and answers nothing before the first read", async () => {
    vi.mocked(api.listRunHistory).mockResolvedValue({ items: [run("running")], total: 1 });
    const { result } = renderHook(() => useRunHistory({ workflowId: "wf", page: 0 }), {
      wrapper,
    });
    expect(result.current.runs).toEqual([]);
    await waitFor(() => expect(result.current.runs).toHaveLength(1));
  });
});

describe("retrying a run", () => {
  it("starts the retry and says so, or says why it could not", async () => {
    vi.mocked(api.getWorkflowRun).mockResolvedValue(run("failed"));
    vi.mocked(api.listWorkflowRunNodes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflowRunGraph).mockResolvedValue(null as never);
    vi.mocked(api.listWorkflowRunFiles).mockResolvedValue({ items: [] });
    vi.mocked(api.retryWorkflowRun)
      .mockResolvedValueOnce({ id: "r2", workflow_id: "wf", status: "running" } as WorkflowRunRead)
      .mockRejectedValueOnce(new Error("no"));
    const { result } = renderHook(() => useWorkflowRun("r"), { wrapper });

    await act(() => result.current.retry.mutateAsync());
    expect(toast.success).toHaveBeenCalledWith("Retry started");
    await act(async () => {
      await result.current.retry.mutateAsync().catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
  });
});

describe("useWorkflowRun", () => {
  it("reads a run with its steps and graph, and cancels it", async () => {
    vi.mocked(api.getWorkflowRun).mockResolvedValue(run("running"));
    vi.mocked(api.listWorkflowRunNodes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflowRunGraph).mockResolvedValue({
      entry_node_id: "a",
      nodes: [],
      edges: [],
      bindings: [],
      scopes: [],
    });
    vi.mocked(api.cancelWorkflowRun).mockResolvedValue(run("cancelled"));
    vi.mocked(api.listWorkflowRunFiles).mockResolvedValue({
      items: [{ id: "f1" } as never],
    });
    const { result } = renderHook(() => useWorkflowRun("r"), { wrapper });
    await waitFor(() => expect(result.current.graph).not.toBeNull());
    await waitFor(() => expect(result.current.files).toHaveLength(1));
    expect(result.current.run?.status).toBe("running");
    await act(() => result.current.cancel.mutateAsync());
    await waitFor(() => expect(result.current.run?.status).toBe("cancelled"));
    expect(toast.success).toHaveBeenCalledWith("Run cancelled");
  });

  it("says why a run could not be cancelled", async () => {
    vi.mocked(api.getWorkflowRun).mockResolvedValue(run("succeeded"));
    vi.mocked(api.listWorkflowRunNodes).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflowRunGraph).mockResolvedValue(null as never);
    vi.mocked(api.cancelWorkflowRun).mockRejectedValue(new Error("no"));
    vi.mocked(api.listWorkflowRunFiles).mockResolvedValue({ items: [] });
    const { result } = renderHook(() => useWorkflowRun("r"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.cancel.mutateAsync().catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
    expect(result.current.nodes).toEqual([]);
  });
});
