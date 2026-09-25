import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import {
  useNodeCatalog,
  useWorkflow,
  useWorkflowVersion,
  useWorkflowVersions,
  useWorkflows,
} from "./use-workflows";
import * as api from "@/lib/workflows/workflows-api";
import { ApiError } from "@/lib/api-error";
import type { WorkflowGraph } from "@/lib/workflows/types";

vi.mock("@/lib/workflows/workflows-api", () => ({
  listWorkflows: vi.fn(),
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  listWorkflowVersions: vi.fn(),
  getWorkflowVersion: vi.fn(),
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

/** A wrapper whose one client's `invalidateQueries` is spied, to read the keys a mutation invalidates. */
function spyWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateQueries = vi.spyOn(client, "invalidateQueries");
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrap, invalidateQueries };
}

/** The `queryKey`s a spied `invalidateQueries` was asked to invalidate, in call order. */
function invalidatedKeys(spy: ReturnType<typeof vi.spyOn>): unknown[] {
  return spy.mock.calls.map(
    (call: unknown[]) => (call[0] as { queryKey?: unknown } | undefined)?.queryKey,
  );
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
    expect(api.listWorkflows).toHaveBeenCalledTimes(1);
    expect(api.listWorkflows).toHaveBeenCalledWith({ skip: 0, limit: 100 });
  });

  it("walks every page so a registry past one page is whole, not its first page", async () => {
    // The route caps `limit` at 100; a registry larger than that is several
    // requests, and reading only the first is the #1787 bug the walk fixes.
    vi.mocked(api.listWorkflows)
      .mockResolvedValueOnce({
        items: [{ id: "wf-1", name: "One" }] as never,
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [{ id: "wf-2", name: "Two" }] as never,
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [{ id: "wf-3", name: "Three" }] as never,
        total: 3,
      });

    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.workflows.map((w) => w.id)).toEqual(["wf-1", "wf-2", "wf-3"]);
    expect(result.current.total).toBe(3);
    expect(api.listWorkflows).toHaveBeenNthCalledWith(1, { skip: 0, limit: 100 });
    expect(api.listWorkflows).toHaveBeenNthCalledWith(2, { skip: 1, limit: 100 });
    expect(api.listWorkflows).toHaveBeenNthCalledWith(3, { skip: 2, limit: 100 });
  });

  it("ends the walk when a page answers nothing, rather than spinning on a stale count", async () => {
    // A workflow deleted mid-walk leaves `total` larger than what is left to read;
    // an empty page ends the walk instead of looping forever.
    vi.mocked(api.listWorkflows)
      .mockResolvedValueOnce({
        items: [{ id: "wf-1", name: "One" }] as never,
        total: 5,
      })
      .mockResolvedValueOnce({ items: [], total: 5 });

    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.workflows.map((w) => w.id)).toEqual(["wf-1"]);
    expect(api.listWorkflows).toHaveBeenCalledTimes(2);
  });

  it("does not re-fetch when the first page is empty despite a nonzero count", async () => {
    // A count without a first page (a race, or a miscounting backend) must not
    // start the walk: `skip=0` already answered nothing, so asking again would
    // loop on the same empty page.
    vi.mocked(api.listWorkflows).mockResolvedValueOnce({ items: [], total: 5 });

    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.workflows).toEqual([]);
    expect(result.current.total).toBe(5);
    expect(api.listWorkflows).toHaveBeenCalledTimes(1);
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

  it("invalidates only the new workflow's detail and the list, not the whole subtree", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.createWorkflow).mockResolvedValue({ id: "wf-2" } as never);
    const { wrap, invalidateQueries } = spyWrapper();
    const { result } = renderHook(() => useWorkflows(), { wrapper: wrap });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    invalidateQueries.mockClear();

    await act(async () => {
      await result.current.create.mutateAsync({ name: "New one" });
    });

    const keys = invalidatedKeys(invalidateQueries);
    expect(keys).toContainEqual(["workflows", "wf-2"]);
    // The bare list prefix, so every walked page is refreshed, not just one.
    expect(keys).toContainEqual(["workflows", "list"]);
    // Never the `all()` root — it would drop the immutable node catalog and every
    // other workflow's frozen versions.
    expect(keys).not.toContainEqual(["workflows"]);
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

  it("seeds the draft graph when created from a template", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.createWorkflow).mockResolvedValue({ id: "wf-3", draft_revision: 0 } as never);
    vi.mocked(api.updateWorkflowDraft).mockResolvedValue({ id: "wf-3" } as never);
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.create.mutateAsync({ name: "From template", graph: GRAPH });
    });

    expect(api.createWorkflow).toHaveBeenCalledWith({ name: "From template" });
    expect(api.updateWorkflowDraft).toHaveBeenCalledWith("wf-3", {
      graph: GRAPH,
      expected_revision: 0,
    });
    expect(toast.success).toHaveBeenCalledWith("Workflow created");
  });

  it("duplicates a workflow by seeding its draft graph into a new one", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1", draft_graph: GRAPH } as never);
    vi.mocked(api.createWorkflow).mockResolvedValue({ id: "wf-copy", draft_revision: 0 } as never);
    vi.mocked(api.updateWorkflowDraft).mockResolvedValue({ id: "wf-copy" } as never);
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      const created = await result.current.duplicate.mutateAsync({
        sourceId: "wf-1",
        name: "Nightly (copy)",
      });
      expect(created.id).toBe("wf-copy");
    });

    expect(api.getWorkflow).toHaveBeenCalledWith("wf-1");
    expect(api.createWorkflow).toHaveBeenCalledWith({ name: "Nightly (copy)" });
    expect(api.updateWorkflowDraft).toHaveBeenCalledWith("wf-copy", {
      graph: GRAPH,
      expected_revision: 0,
    });
    expect(toast.success).toHaveBeenCalledWith("Workflow duplicated");
  });

  it("duplicates a graphless workflow without a draft write", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1", draft_graph: null } as never);
    vi.mocked(api.createWorkflow).mockResolvedValue({ id: "wf-copy", draft_revision: 0 } as never);
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.duplicate.mutateAsync({ sourceId: "wf-1", name: "Empty (copy)" });
    });

    expect(api.updateWorkflowDraft).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("Workflow duplicated");
  });

  it("toasts a duplicate failure", async () => {
    vi.mocked(api.listWorkflows).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.getWorkflow).mockRejectedValue(new ApiError(404, "Gone"));
    const { result } = renderHook(() => useWorkflows(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.duplicate
        .mutateAsync({ sourceId: "wf-x", name: "x" })
        .catch(() => undefined);
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

  it("invalidates only this workflow's detail and the list on a draft save", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1" } as never);
    vi.mocked(api.updateWorkflowDraft).mockResolvedValue({
      id: "wf-1",
      draft_revision: 4,
    } as never);
    const { wrap, invalidateQueries } = spyWrapper();
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper: wrap });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    invalidateQueries.mockClear();

    await act(async () => {
      await result.current.saveDraft.mutateAsync({ graph: GRAPH, expected_revision: 3 });
    });

    const keys = invalidatedKeys(invalidateQueries);
    expect(keys).toContainEqual(["workflows", "wf-1"]);
    expect(keys).toContainEqual(["workflows", "list"]);
    expect(keys).not.toContainEqual(["workflows"]);
  });

  it("invalidates only this workflow's detail and the list on publish", async () => {
    vi.mocked(api.getWorkflow).mockResolvedValue({ id: "wf-1" } as never);
    vi.mocked(api.publishWorkflow).mockResolvedValue({ id: "v1", version: 2 } as never);
    const { wrap, invalidateQueries } = spyWrapper();
    const { result } = renderHook(() => useWorkflow("wf-1"), { wrapper: wrap });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    invalidateQueries.mockClear();

    await act(async () => {
      await result.current.publish.mutateAsync({ note: null, expected_revision: 3 });
    });

    const keys = invalidatedKeys(invalidateQueries);
    expect(keys).toContainEqual(["workflows", "wf-1"]);
    expect(keys).toContainEqual(["workflows", "list"]);
    expect(keys).not.toContainEqual(["workflows"]);
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

describe("useWorkflowVersion", () => {
  it("fetches one version's frozen graph when a version is selected", async () => {
    vi.mocked(api.getWorkflowVersion).mockResolvedValue({ id: "v1", version: 1 } as never);
    const { result } = renderHook(() => useWorkflowVersion("wf-1", "v1"), { wrapper });
    await waitFor(() => expect(result.current.version).toEqual({ id: "v1", version: 1 }));
    expect(api.getWorkflowVersion).toHaveBeenCalledWith("wf-1", "v1");
  });

  it("does not fetch until a version is selected", async () => {
    const { result } = renderHook(() => useWorkflowVersion("wf-1", null), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.version).toBeUndefined();
    expect(api.getWorkflowVersion).not.toHaveBeenCalled();
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
