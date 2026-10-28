import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { listRunLogs, listWorkflowLogs } from "./logs-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn() } };
});

beforeEach(() => vi.clearAllMocks());

describe("logs-api", () => {
  it("reads the first page of a workflow's log with no filter", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflowLogs({ workflowId: "wf", includeTest: false, page: 0 });
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf/logs", {
      params: { skip: "0", limit: "50" },
    });
  });

  it("sends each filter under the name the route reads, and the page as an offset", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflowLogs({
      workflowId: "wf",
      nodeInstanceId: "n1",
      outcome: "error",
      from: "2026-10-01T00:00:00.000Z",
      q: "timeout",
      includeTest: true,
      page: 2,
    });
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf/logs", {
      params: {
        skip: "100",
        limit: "50",
        node_instance_id: "n1",
        outcome: "error",
        from: "2026-10-01T00:00:00.000Z",
        q: "timeout",
        include_test: "true",
      },
    });
  });

  it("sends a run filter as `run`, and leaves an empty one out", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflowLogs({ workflowId: "wf", run: "3f2a-9", includeTest: false, page: 0 });
    await listWorkflowLogs({ workflowId: "wf", run: "", includeTest: false, page: 0 });
    expect(vi.mocked(apiClient.get).mock.calls[0]?.[1]).toEqual({
      params: { skip: "0", limit: "50", run: "3f2a-9" },
    });
    expect(vi.mocked(apiClient.get).mock.calls[1]?.[1]).toEqual({
      params: { skip: "0", limit: "50" },
    });
  });

  it("leaves an empty search out", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflowLogs({ workflowId: "wf", q: "", includeTest: false, page: 0 });
    expect(vi.mocked(apiClient.get).mock.calls[0]?.[1]).toEqual({
      params: { skip: "0", limit: "50" },
    });
  });

  it("reads every page of a run's lines, and stops when the run shrank", async () => {
    const entry = (id: string) => ({ id }) as never;
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ items: [entry("a"), entry("b")], total: 5 })
      .mockResolvedValueOnce({ items: [entry("c")], total: 5 })
      .mockResolvedValueOnce({ items: [], total: 5 });
    const list = await listRunLogs("r1");
    expect(list.items.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(apiClient.get).toHaveBeenLastCalledWith("/workflow-runs/r1/logs", {
      params: { skip: "3", limit: "500" },
    });
  });
});
