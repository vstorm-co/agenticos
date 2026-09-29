import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import {
  cancelWorkflowRun,
  getWorkflowRun,
  getWorkflowRunGraph,
  listWorkflowRunNodes,
  listWorkflowRuns,
  startWorkflowRun,
} from "./runs-api";
import { isRunTerminal } from "./types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});

beforeEach(() => vi.clearAllMocks());

describe("runs-api", () => {
  it("lists one workflow's runs", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflowRuns("wf");
    expect(apiClient.get).toHaveBeenCalledWith("/workflow-runs", {
      params: { workflow_id: "wf", limit: "100" },
    });
  });

  it("reads a run, its steps and the graph it executes", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ id: "r" })
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ graph: { entry_node_id: "a" } });
    await expect(getWorkflowRun("r")).resolves.toEqual({ id: "r" });
    await listWorkflowRunNodes("r");
    expect(apiClient.get).toHaveBeenLastCalledWith("/workflow-runs/r/nodes", {
      params: { limit: "500" },
    });
    await expect(getWorkflowRunGraph("r")).resolves.toEqual({ entry_node_id: "a" });
  });

  it("starts and cancels a run", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r" });
    await startWorkflowRun({ workflow_id: "wf", mode: "test", input: { a: 1 } });
    expect(apiClient.post).toHaveBeenCalledWith("/workflow-runs", {
      workflow_id: "wf",
      mode: "test",
      input: { a: 1 },
    });
    await cancelWorkflowRun("r");
    expect(apiClient.post).toHaveBeenLastCalledWith("/workflow-runs/r/cancel");
  });
});

describe("isRunTerminal", () => {
  it("tells a run that ended from one still moving", () => {
    expect(isRunTerminal("succeeded")).toBe(true);
    expect(isRunTerminal("budget_exceeded")).toBe(true);
    expect(isRunTerminal("waiting_approval")).toBe(false);
  });
});
