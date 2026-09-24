import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { NodeDefinition, WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useWorkflowAutosave } from "./use-workflow-autosave";

const GRAPH: WorkflowGraph = {
  entry_node_id: "n1",
  nodes: [
    {
      id: "n1",
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

const DEFINITION: NodeDefinition = {
  id: "debug.echo",
  version: 1,
  name: "Echo",
  category: "debug",
  description: "",
  kind: "action",
  config_schema: null,
  input_schema: null,
  output_schema: null,
  ports: [],
  effect_kind: "pure",
  retry_guarantee: "none",
  scopes: [],
};

/** A saved detail carrying the next revision. */
function detail(revision: number): WorkflowDetail {
  return {
    id: "w1",
    slug: "w",
    name: "W",
    description: null,
    status: "draft",
    visibility: "org",
    owner_user_id: null,
    current_version_id: null,
    draft_revision: revision,
    created_at: null,
    updated_at: null,
    draft_graph: GRAPH,
  };
}

/** The `409` the draft route answers a stale write with. */
function conflict(currentRevision: number | null): ApiError {
  const details = currentRevision === null ? {} : { current_revision: currentRevision };
  return new ApiError(409, "conflict", {
    error: { code: "REVISION_CONFLICT", message: "conflict", details },
  });
}

/** A deferred promise, so a test can resolve a save when it chooses. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function seedLoaded(revision = 0) {
  act(() => {
    useWorkflowEditorStore.getState().load({ workflowId: "w1", expectedRevision: revision });
    useWorkflowEditorStore.getState().seedGraph(GRAPH);
  });
}

beforeEach(() => {
  act(() => useWorkflowEditorStore.getState().teardown());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useWorkflowAutosave", () => {
  it("is idle until the draft is dirtied, then pending", () => {
    seedLoaded();
    const saveDraft = vi.fn();
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));
    expect(result.current).toBe("idle");
    act(() => useWorkflowEditorStore.getState().markDirty());
    expect(result.current).toBe("pending");
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("saves the current graph against the last revision and marks it saved", async () => {
    seedLoaded(3);
    const saveDraft = vi.fn().mockResolvedValue(detail(4));
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());

    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));
    expect(saveDraft).toHaveBeenCalledWith({ graph: GRAPH, expected_revision: 3 });
    await waitFor(() => expect(result.current).toBe("saved"));
    const store = useWorkflowEditorStore.getState();
    expect(store.isDirty).toBe(false);
    expect(store.expectedRevision).toBe(4);
  });

  it("coalesces a burst of edits into a single save of the final graph", async () => {
    seedLoaded(0);
    const saveDraft = vi.fn().mockResolvedValue(detail(1));
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 20 }));

    act(() => {
      useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 1, y: 1 });
      useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 2, y: 2 });
    });

    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));
    const sent = saveDraft.mock.calls[0]![0].graph as WorkflowGraph;
    expect(sent.nodes).toHaveLength(3);
  });

  it("drops a save whose editor instance was replaced before it resolved", async () => {
    seedLoaded(0);
    const gate = deferred<WorkflowDetail>();
    const saveDraft = vi.fn().mockReturnValue(gate.promise);
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));

    // A remount / workflow switch bumps the generation while the save is in flight.
    act(() => useWorkflowEditorStore.getState().load({ workflowId: "w1", expectedRevision: 9 }));
    await act(async () => {
      gate.resolve(detail(1));
      await gate.promise;
    });

    // The stale result never advances the revision the new instance loaded.
    expect(useWorkflowEditorStore.getState().expectedRevision).toBe(9);
  });

  it("keeps the draft dirty when the graph changed while the save was in flight", async () => {
    seedLoaded(0);
    const gate = deferred<WorkflowDetail>();
    const saveDraft = vi.fn().mockReturnValueOnce(gate.promise).mockResolvedValue(detail(2));
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));

    // An edit lands mid-flight, so the resolved save must not clear the dirty flag.
    act(() => useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 5, y: 5 }));
    await act(async () => {
      gate.resolve(detail(1));
      await gate.promise;
    });

    await waitFor(() => expect(useWorkflowEditorStore.getState().expectedRevision).toBe(1));
    expect(useWorkflowEditorStore.getState().isDirty).toBe(true);
    // The newer graph then saves against the revision the first write produced.
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(2));
    expect(saveDraft.mock.calls[1]![0].expected_revision).toBe(1);
  });

  it("raises the conflict banner on a 409 and pauses autosave", async () => {
    seedLoaded(0);
    const saveDraft = vi.fn().mockRejectedValue(conflict(7));
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());

    await waitFor(() =>
      expect(useWorkflowEditorStore.getState().conflict).toEqual({ currentRevision: 7 }),
    );
    expect(result.current).toBe("conflict");

    // Paused: a further edit does not dispatch while the conflict stands.
    act(() => useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 1, y: 1 }));
    await new Promise((r) => setTimeout(r, 20));
    expect(saveDraft).toHaveBeenCalledTimes(1);
  });

  it("shows an error and retries on the next edit for a non-conflict failure", async () => {
    seedLoaded(0);
    const saveDraft = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(500, "boom", { error: { code: "X", message: "boom", details: null } }),
      )
      .mockResolvedValue(detail(1));
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(result.current).toBe("error"));

    act(() => useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 1, y: 1 }));
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(2));
  });

  it("drops a rejected save whose editor instance was already replaced", async () => {
    seedLoaded(0);
    const gate = deferred<WorkflowDetail>();
    const saveDraft = vi.fn().mockReturnValue(gate.promise);
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));

    act(() => useWorkflowEditorStore.getState().load({ workflowId: "w1", expectedRevision: 9 }));
    await act(async () => {
      gate.reject(conflict(3));
      await gate.promise.catch(() => undefined);
    });

    // A stale rejection raises no banner on the instance that replaced it.
    expect(useWorkflowEditorStore.getState().conflict).toBeNull();
    expect(useWorkflowEditorStore.getState().expectedRevision).toBe(9);
  });

  it("shows an error for a failure that is not an ApiError", async () => {
    seedLoaded(0);
    const saveDraft = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(result.current).toBe("error"));
    expect(useWorkflowEditorStore.getState().conflict).toBeNull();
  });

  it("treats a 409 that names no current revision as an error, not a conflict", async () => {
    seedLoaded(0);
    const saveDraft = vi.fn().mockRejectedValue(conflict(null));
    const { result } = renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));

    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(result.current).toBe("error"));
    expect(useWorkflowEditorStore.getState().conflict).toBeNull();
  });

  it("does not save before the graph is seeded", async () => {
    act(() => useWorkflowEditorStore.getState().load({ workflowId: "w1", expectedRevision: 0 }));
    const saveDraft = vi.fn();
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));
    act(() => useWorkflowEditorStore.getState().markDirty());
    await new Promise((r) => setTimeout(r, 20));
    expect(saveDraft).not.toHaveBeenCalled();
  });

  it("does not save before a revision is known", async () => {
    act(() => useWorkflowEditorStore.getState().seedGraph(GRAPH));
    const saveDraft = vi.fn();
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));
    act(() => useWorkflowEditorStore.getState().markDirty());
    await new Promise((r) => setTimeout(r, 20));
    expect(saveDraft).not.toHaveBeenCalled();
  });
});
