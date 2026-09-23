import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useNodeCatalog, useWorkflow, useWorkflowVersions, useWorkflows } from "./use-workflows";
import * as api from "@/lib/workflows/workflows-api";
import { ApiError } from "@/lib/api-error";
import type { WorkflowGraph } from "@/lib/workflows/types";

vi.mock("@/lib/workflows/workflows-api", () => ({
  listWorkflows: vi.fn(),
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  listWorkflowVersions: vi.fn(),
  updateWorkflowDraft: vi.fn(),
  publishWorkflow: vi.fn(),
  getNodeCatalog: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const GRAPH: WorkflowGraph = {
  entry_node_id: "n1",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

beforeEach(() => vi.clearAllMocks());

describe("useWorkflows", () => {
  it("lists the workflows the caller can see", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({
      items: [{ id: "wf-1", name: "Nightly" }] as never,
      total: 1,
    });
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.workflows).toEqual([{ id: "wf-1", name: "Nightly" }]);
    expect(result.current.total).toBe(1);
  });

  it("stays out of the network and reports empty when disabled", async () => {
    const { result } = renderHook(() => useWorkflows({ enabled: false }), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.workflows).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(api.listWorkflows).not.toHaveBeenCalled();
  });

  it("creates a workflow and toasts", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.createWorkflow).mockResolvedValue({ id: "wf-2" } as never);
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.create.mutateAsync({ name: "New one" });
    });

    expect(api.createWorkflow).toHaveBeenCalledWith({ name: "New one" });
    expect(toast.success).toHaveBeenCalledWith("Workflow created");
  });

  it("toasts a create failure", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.createWorkflow).mockRejectedValue(new ApiError(409, "Name taken"));
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.create.mutateAsync({ name: "Dup" }).catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalled();
  });
});

describe("useWorkflow", () => {
  it("loads one workflow with its draft graph", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1", draft_graph: GRAPH } as never);
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.workflow).toEqual({ id: "wf-1", draft_graph: GRAPH });
  });

  it("does not fetch for a null id", async () => {
    const { result } = renderHook(() => useWorkflow(null), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.workflow).toBeUndefined();
    expect(api.getWorkflow).not.toHaveBeenCalled();
  });

  it("saves the draft against the expected revision", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1" } as never);
    vi.mocked(api.updateWorkflowDraft).mockResolvedValue({
      id: "wf-1",
      draft_revision: 4,
    } as never);
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.saveDraft.mutateAsync({ graph: GRAPH, expected_revision: 3 });
    });

    expect(api.updateWorkflowDraft).toHaveBeenCalledWith("wf-1", {
      graph: GRAPH,
      expected_revision: 3,
    });
  });

  it("publishes and toasts the version", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1" } as never);
    vi.mocked(api.publishWorkflow).mockResolvedValue({ id: "v1", version: 2 } as never);
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.publish.mutateAsync({ note: null, expected_revision: 3 });
    });

    expect(toast.success).toHaveBeenCalledWith("Published version 2");
  });

  it("toasts a publish failure", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1" } as never);
    vi.mocked(api.publishWorkflow).mockRejectedValue(new ApiError(409, "Conflict"));
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.publish
        .mutateAsync({ note: null, expected_revision: 3 })
        .catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalled();
  });
});

describe("useWorkflowVersions", () => {
  it("lists a workflow's versions", async () => {
    vi.mocked(api.listWorkflowVersions).mockResolvedValue({
      items: [{ id: "v1", version: 1 }] as never,
    });
    const { result } = renderHook(() => useWorkflowVersions("wf-1"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.versions).toEqual([{ id: "v1", version: 1 }]);
  });

  it("does not fetch for a null id", async () => {
    const { result } = renderHook(() => useWorkflowVersions(null), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.versions).toEqual([]);
    expect(api.listWorkflowVersions).not.toHaveBeenCalled();
  });
});

describe("useNodeCatalog", () => {
  it("exposes the registered node types", async () => {
    vi.mocked(api.getNodeCatalog).mockResolvedValue({
      items: [{ id: "debug.echo" }] as never,
      total: 1,
    });
    const { result } = renderHook(() => useNodeCatalog(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.nodes).toEqual([{ id: "debug.echo" }]);
  });

  it("reports an empty catalog while the request is still in flight", () => {
    vi.mocked(api.getNodeCatalog).mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useNodeCatalog(), { wrapper });
    expect(result.current.nodes).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });
});
