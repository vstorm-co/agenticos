import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";
import type { WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";
import { getWorkflow } from "@/lib/workflows/workflows-api";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ConflictBanner } from "./conflict-banner";

vi.mock("@/lib/workflows/workflows-api", () => ({ getWorkflow: vi.fn() }));

const LOCAL_GRAPH: WorkflowGraph = {
  entry_node_id: "local",
  nodes: [
    {
      id: "local",
      definition_id: "debug.echo",
      definition_version: 1,
      config: {},
      layout: { x: 0, y: 0 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

const SERVER_GRAPH: WorkflowGraph = {
  entry_node_id: "server",
  nodes: [
    {
      id: "server",
      definition_id: "debug.echo",
      definition_version: 1,
      config: {},
      layout: { x: 1, y: 1 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

function serverDetail(): WorkflowDetail {
  return {
    id: "w1",
    slug: "w",
    name: "W",
    description: null,
    status: "draft",
    visibility: "org",
    owner_user_id: null,
    current_version_id: null,
    draft_revision: 12,
    created_at: null,
    updated_at: null,
    draft_graph: SERVER_GRAPH,
  };
}

function renderBanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<ConflictBanner workflowId="w1" />, { wrapper });
}

beforeEach(() => {
  act(() => {
    const store = useWorkflowEditorStore.getState();
    store.teardown();
    store.load({ workflowId: "w1", expectedRevision: 4 });
    store.seedGraph(LOCAL_GRAPH);
    store.markDirty();
  });
  vi.mocked(getWorkflow).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ConflictBanner", () => {
  it("renders nothing while there is no conflict", () => {
    const { container } = renderBanner();
    expect(container.querySelector("[data-workflow-conflict]")).toBeNull();
  });

  it("overwrite resends against the server revision and keeps local edits", async () => {
    renderBanner();
    act(() => useWorkflowEditorStore.getState().setConflict(9));
    expect(await screen.findByText("This draft changed elsewhere")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Overwrite" }));

    const store = useWorkflowEditorStore.getState();
    expect(store.conflict).toBeNull();
    expect(store.expectedRevision).toBe(9);
    // Local edits are kept, not discarded.
    expect(store.isDirty).toBe(true);
    expect(store.getGraph()).toBe(LOCAL_GRAPH);
  });

  it("reload replaces the draft with the server's copy and clears the conflict", async () => {
    vi.mocked(getWorkflow).mockResolvedValue(serverDetail());
    renderBanner();
    act(() => useWorkflowEditorStore.getState().setConflict(9));

    await userEvent.click(await screen.findByRole("button", { name: "Reload" }));

    await waitFor(() => expect(useWorkflowEditorStore.getState().conflict).toBeNull());
    const store = useWorkflowEditorStore.getState();
    expect(store.getGraph()?.entry_node_id).toBe("server");
    expect(store.expectedRevision).toBe(12);
    expect(store.isDirty).toBe(false);
    expect(getWorkflow).toHaveBeenCalledWith("w1");
  });

  it("reload fetches the server copy even when the detail is fresh in the cache", async () => {
    // The 5-minute global stale window in practice: seed the client's OWN cached
    // draft — the stale copy the 409 is about — as a fresh query. Without
    // `staleTime: 0` on the reload's `fetchQuery`, TanStack would serve this
    // cached copy and never call `getWorkflow`, so Reload could not escape the
    // conflict.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
    });
    const staleDetail: WorkflowDetail = {
      ...serverDetail(),
      draft_graph: LOCAL_GRAPH,
      draft_revision: 4,
    };
    client.setQueryData(qk.workflows.detail("w1"), staleDetail);
    vi.mocked(getWorkflow).mockResolvedValue(serverDetail());
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    render(<ConflictBanner workflowId="w1" />, { wrapper });
    act(() => useWorkflowEditorStore.getState().setConflict(9));

    await userEvent.click(await screen.findByRole("button", { name: "Reload" }));

    await waitFor(() => expect(useWorkflowEditorStore.getState().conflict).toBeNull());
    // The server was actually read, not served the client's stale cache.
    expect(getWorkflow).toHaveBeenCalledWith("w1");
    const store = useWorkflowEditorStore.getState();
    expect(store.getGraph()?.entry_node_id).toBe("server");
    expect(store.expectedRevision).toBe(12);
    expect(store.isDirty).toBe(false);
  });

  it("reloads a workflow whose server draft is empty", async () => {
    vi.mocked(getWorkflow).mockResolvedValue({ ...serverDetail(), draft_graph: null });
    renderBanner();
    act(() => useWorkflowEditorStore.getState().setConflict(9));

    await userEvent.click(await screen.findByRole("button", { name: "Reload" }));

    await waitFor(() => expect(useWorkflowEditorStore.getState().conflict).toBeNull());
    expect(useWorkflowEditorStore.getState().getGraph()?.entry_node_id).toBe("");
  });

  it("disables the controls while a reload is in flight", async () => {
    let resolve!: (value: WorkflowDetail) => void;
    vi.mocked(getWorkflow).mockReturnValue(new Promise((r) => (resolve = r)));
    renderBanner();
    act(() => useWorkflowEditorStore.getState().setConflict(9));

    await userEvent.click(await screen.findByRole("button", { name: "Reload" }));

    expect(screen.getByRole("button", { name: "Reload" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Overwrite" })).toBeDisabled();

    await act(async () => {
      resolve(serverDetail());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(screen.queryByText("This draft changed elsewhere")).not.toBeInTheDocument(),
    );
  });
});
