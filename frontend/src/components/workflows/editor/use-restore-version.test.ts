import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { ApiError } from "@/lib/api-error";
import type {
  NodeDefinition,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowVersionRead,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useRestoreVersion } from "./use-restore-version";
import { useWorkflowAutosave } from "./use-workflow-autosave";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function graph(entry: string): WorkflowGraph {
  return {
    entry_node_id: entry,
    nodes: [
      {
        id: entry,
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
}

const DRAFT = graph("draft");
const RESTORED = graph("v1");

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

const VERSION: WorkflowVersionRead = {
  id: "v-1",
  version: 1,
  note: null,
  published_by_user_id: null,
  budget_limit: null,
  created_at: null,
};

function detail(revision: number, draft: WorkflowGraph | null = RESTORED): WorkflowDetail {
  return {
    id: "w1",
    slug: "w",
    name: "W",
    description: null,
    status: "published",
    visibility: "org",
    owner_user_id: null,
    current_version_id: null,
    draft_revision: revision,
    created_at: null,
    updated_at: null,
    draft_graph: draft,
  };
}

function conflict(currentRevision: number): ApiError {
  return new ApiError(409, "conflict", {
    error: {
      code: "REVISION_CONFLICT",
      message: "conflict",
      details: { current_revision: currentRevision },
    },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function seedLoaded(revision: number) {
  act(() => {
    useWorkflowEditorStore.getState().load({ workflowId: "w1", expectedRevision: revision });
    useWorkflowEditorStore.getState().seedGraph(DRAFT);
  });
}

beforeEach(() => {
  act(() => useWorkflowEditorStore.getState().teardown());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useRestoreVersion", () => {
  it("restores against the draft's revision and makes the returned draft the working copy", async () => {
    seedLoaded(4);
    act(() => useWorkflowEditorStore.getState().addNode(DEFINITION, { x: 5, y: 5 }));
    expect(useWorkflowEditorStore.getState().history.canUndo).toBe(true);
    const restore = vi.fn().mockResolvedValue(detail(5));
    const { result } = renderHook(() => useRestoreVersion(restore));

    let landed = false;
    await act(async () => {
      landed = await result.current(VERSION);
    });

    expect(landed).toBe(true);
    expect(restore).toHaveBeenCalledWith({ versionId: "v-1", expectedRevision: 4 });
    const store = useWorkflowEditorStore.getState();
    expect(store.graph).toEqual(RESTORED);
    expect(store.expectedRevision).toBe(5);
    expect(store.isDirty).toBe(false);
    // The undo stack starts over from the restored graph.
    expect(store.history).toEqual({ canUndo: false, canRedo: false });
    expect(toast.success).toHaveBeenCalledWith("Version 1 is the draft again");
  });

  it("falls back to an empty graph when the restored draft has none", async () => {
    seedLoaded(0);
    const restore = vi.fn().mockResolvedValue(detail(1, null));
    const { result } = renderHook(() => useRestoreVersion(restore));

    await act(async () => {
      await result.current(VERSION);
    });

    expect(useWorkflowEditorStore.getState().graph?.nodes).toEqual([]);
  });

  it("stops a queued autosave from writing the old graph over the restored one", async () => {
    seedLoaded(2);
    const saveDraft = vi.fn();
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 30 }));
    const restore = vi.fn().mockResolvedValue(detail(3));
    const { result } = renderHook(() => useRestoreVersion(restore));

    // An edit is waiting out the debounce when the restore is confirmed.
    act(() => useWorkflowEditorStore.getState().markDirty());
    await act(async () => {
      await result.current(VERSION);
    });
    await new Promise((resolve) => setTimeout(resolve, 60));

    expect(saveDraft).not.toHaveBeenCalled();
    expect(useWorkflowEditorStore.getState().graph).toEqual(RESTORED);
  });

  it("drops a save already in flight so it cannot land on the restored draft", async () => {
    seedLoaded(2);
    const gate = deferred<WorkflowDetail>();
    const saveDraft = vi.fn().mockReturnValue(gate.promise);
    renderHook(() => useWorkflowAutosave({ saveDraft, debounceMs: 5 }));
    act(() => useWorkflowEditorStore.getState().markDirty());
    await waitFor(() => expect(saveDraft).toHaveBeenCalledTimes(1));

    const restore = vi.fn().mockResolvedValue(detail(7));
    const { result } = renderHook(() => useRestoreVersion(restore));
    await act(async () => {
      await result.current(VERSION);
    });
    await act(async () => {
      gate.resolve(detail(3, DRAFT));
      await gate.promise;
    });

    const store = useWorkflowEditorStore.getState();
    expect(store.graph).toEqual(RESTORED);
    expect(store.expectedRevision).toBe(7);
  });

  it("raises the conflict banner on a 409 and puts unsaved edits back in line", async () => {
    seedLoaded(2);
    act(() => useWorkflowEditorStore.getState().markDirty());
    const restore = vi.fn().mockRejectedValue(conflict(3));
    const { result } = renderHook(() => useRestoreVersion(restore));

    let landed = true;
    await act(async () => {
      landed = await result.current(VERSION);
    });

    expect(landed).toBe(false);
    const store = useWorkflowEditorStore.getState();
    expect(store.conflict).toEqual({ currentRevision: 3 });
    expect(store.isDirty).toBe(true);
    expect(store.graph).toEqual(DRAFT);
    expect(toast.error).toHaveBeenCalledWith(
      "The draft changed while restoring. Resolve the conflict, then restore again.",
    );
  });

  it("leaves a clean draft clean when another refusal comes back", async () => {
    seedLoaded(2);
    const restore = vi.fn().mockRejectedValue(new ApiError(500, "boom"));
    const { result } = renderHook(() => useRestoreVersion(restore));

    let landed = true;
    await act(async () => {
      landed = await result.current(VERSION);
    });

    expect(landed).toBe(false);
    const store = useWorkflowEditorStore.getState();
    expect(store.isDirty).toBe(false);
    expect(store.conflict).toBeNull();
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("sends nothing before the editor has loaded a draft", async () => {
    const restore = vi.fn();
    const { result } = renderHook(() => useRestoreVersion(restore));

    let landed = true;
    await act(async () => {
      landed = await result.current(VERSION);
    });

    expect(landed).toBe(false);
    expect(restore).not.toHaveBeenCalled();
  });
});
