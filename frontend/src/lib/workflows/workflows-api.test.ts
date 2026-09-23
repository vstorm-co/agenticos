import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import {
  createWorkflow,
  getNodeCatalog,
  getWorkflow,
  listWorkflowVersions,
  listWorkflows,
  publishWorkflow,
  updateWorkflowDraft,
} from "./workflows-api";
import type { WorkflowDetail, WorkflowGraph } from "./types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

const GRAPH: WorkflowGraph = {
  entry_node_id: "00000000-0000-0000-0000-000000000001",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

describe("workflows-api", () => {
  it("fetches the node catalog", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await expect(getNodeCatalog()).resolves.toEqual({ items: [], total: 0 });
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/node-catalog");
  });

  it("lists workflows with no pagination params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflows();
    expect(apiClient.get).toHaveBeenCalledWith("/workflows", undefined);
  });

  it("lists workflows with only a skip, defaulting the limit", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflows({ skip: 5 });
    expect(apiClient.get).toHaveBeenCalledWith("/workflows", {
      params: { skip: "5", limit: "50" },
    });
  });

  it("lists workflows with only a limit, defaulting the skip", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listWorkflows({ limit: 10 });
    expect(apiClient.get).toHaveBeenCalledWith("/workflows", {
      params: { skip: "0", limit: "10" },
    });
  });

  it("creates a workflow", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "wf-1" });
    await createWorkflow({ name: "Nightly report" });
    expect(apiClient.post).toHaveBeenCalledWith("/workflows", { name: "Nightly report" });
  });

  it("gets one workflow with its draft graph", async () => {
    const detail = { id: "wf-1", draft_graph: GRAPH } as unknown as WorkflowDetail;
    vi.mocked(apiClient.get).mockResolvedValue(detail);
    await expect(getWorkflow("wf-1")).resolves.toBe(detail);
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf-1");
  });

  it("lists a workflow's versions", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [] });
    await listWorkflowVersions("wf-1");
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf-1/versions");
  });

  it("updates the draft graph against the expected revision", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "wf-1" });
    await updateWorkflowDraft("wf-1", { graph: GRAPH, expected_revision: 3 });
    expect(apiClient.patch).toHaveBeenCalledWith("/workflows/wf-1/draft", {
      graph: GRAPH,
      expected_revision: 3,
    });
  });

  it("publishes the draft", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "v1", version: 1 });
    await publishWorkflow("wf-1", { note: "first", expected_revision: 3 });
    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf-1/publish", {
      note: "first",
      expected_revision: 3,
    });
  });
});
