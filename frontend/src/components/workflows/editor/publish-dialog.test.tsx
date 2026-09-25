import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEBUG_ECHO, echo, graph } from "@/components/workflows/validation/fixtures";
import { ApiError } from "@/lib/api-error";
import type { WorkflowGraph, WorkflowVersionRead } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { PublishDialog } from "./publish-dialog";

const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

const VALID_GRAPH = graph({ entry: "a", nodes: [echo("a")] });

function publishedVersion(): WorkflowVersionRead {
  return {
    id: "v1",
    version: 1,
    note: null,
    published_by_user_id: null,
    budget_limit: null,
    created_at: null,
  };
}

function seed(graphValue: WorkflowGraph | null, revision: number | null) {
  act(() => {
    const store = useWorkflowEditorStore.getState();
    store.teardown();
    if (revision !== null) store.load({ workflowId: "w1", expectedRevision: revision });
    if (graphValue !== null) store.seedGraph(graphValue);
  });
}

function graphError(field: string, message: string): ApiError {
  return new ApiError(422, "invalid", {
    error: { code: "GRAPH_INVALID", message: "invalid", details: { fields: [{ field, message }] } },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PublishDialog", () => {
  it("blocks the confirm while the client validation finds a problem", async () => {
    seed(EMPTY_GRAPH, 0);
    const publish = vi.fn();
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));

    expect(screen.getByText("Fix the problems below before publishing.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Publish version" })).toBeDisabled();
    expect(publish).not.toHaveBeenCalled();
  });

  it("publishes a valid draft with the note against the current revision", async () => {
    seed(VALID_GRAPH, 2);
    const publish = vi.fn().mockResolvedValue(publishedVersion());
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.type(screen.getByLabelText("Release note"), "Ship it");
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    await waitFor(() =>
      expect(publish).toHaveBeenCalledWith({ note: "Ship it", expected_revision: 2 }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("surfaces a server refusal on the offending node and selects it on click", async () => {
    seed(VALID_GRAPH, 5);
    const publish = vi.fn().mockRejectedValue(graphError("nodes.a", "This node lost its resource"));
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    // No note typed: the empty note is sent as null.
    await waitFor(() => expect(publish).toHaveBeenCalledWith({ note: null, expected_revision: 5 }));

    await userEvent.click(await screen.findByRole("button", { expanded: false }));
    expect(screen.getByText("This node lost its resource")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: /This node lost its resource/ }));
    expect(useWorkflowEditorStore.getState().selection.nodeIds).toEqual(["a"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("maps edge- and graph-scoped server problems for display", async () => {
    seed(VALID_GRAPH, 1);
    const error = new ApiError(422, "invalid", {
      error: {
        code: "GRAPH_INVALID",
        message: "invalid",
        details: {
          fields: [
            { field: "edges.e1", message: "This edge crosses a scope" },
            { field: "bindings.0", message: "This binding is unavailable" },
            { field: "root", message: "The graph is empty" },
          ],
        },
      },
    });
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn().mockRejectedValue(error)} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    await userEvent.click(await screen.findByRole("button", { expanded: false }));
    expect(screen.getByText("This edge crosses a scope")).toBeVisible();
    expect(screen.getByText("This binding is unavailable")).toBeVisible();
    expect(screen.getByText("The graph is empty")).toBeVisible();
  });

  it("surfaces a revision conflict through the store and closes the dialog", async () => {
    // A publish into a stale revision comes back `409 REVISION_CONFLICT`,
    // carrying the current revision but no field problems. It must reach the
    // shared conflict banner (via the store), not vanish for want of a field.
    seed(VALID_GRAPH, 3);
    const conflict = new ApiError(409, "conflict", {
      error: {
        code: "REVISION_CONFLICT",
        message: "conflict",
        details: { current_revision: 7 },
      },
    });
    const publish = vi.fn().mockRejectedValue(conflict);
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    await waitFor(() => expect(publish).toHaveBeenCalledWith({ note: null, expected_revision: 3 }));
    await waitFor(() =>
      expect(useWorkflowEditorStore.getState().conflict).toEqual({ currentRevision: 7 }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("treats a 409 without a current revision as an ordinary refusal", async () => {
    // Defensive: a `409` that carries no numeric `current_revision` cannot seed
    // the conflict banner, so it falls through to the normal problem handling
    // and the dialog stays open rather than closing on nothing.
    seed(VALID_GRAPH, 4);
    const conflict = new ApiError(409, "conflict", {
      error: { code: "REVISION_CONFLICT", message: "conflict", details: {} },
    });
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn().mockRejectedValue(conflict)} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(useWorkflowEditorStore.getState().conflict).toBeNull();
  });

  it("does nothing when a revision is not yet known", async () => {
    seed(VALID_GRAPH, null);
    const publish = vi.fn();
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    expect(publish).not.toHaveBeenCalled();
  });

  it("runs no client validation before a graph is seeded", async () => {
    seed(null, 0);
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    expect(screen.queryByText("Fix the problems below before publishing.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish version" })).toBeEnabled();
  });

  it("disables the publish trigger while the draft is still saving", async () => {
    // A dirty draft means the last edit has not reached the server, so publishing
    // now would freeze a stale draft and drop the local edits (#1787). The trigger
    // is disabled until the save lands, so the dialog cannot even be opened.
    seed(VALID_GRAPH, 2);
    act(() => useWorkflowEditorStore.getState().markDirty());
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Publish/ })).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("blocks the confirm and shows a hint when the draft turns dirty mid-dialog", async () => {
    // The dialog is opened while the draft is clean, then an autosave-triggering
    // edit lands (the ~400ms debounce or an in-flight PATCH). The confirm must
    // block and a hint must appear rather than freezing the stale server draft.
    seed(VALID_GRAPH, 2);
    const publish = vi.fn();
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    expect(screen.getByRole("button", { name: "Publish version" })).toBeEnabled();

    act(() => useWorkflowEditorStore.getState().markDirty());

    expect(screen.getByText("Finishing save…")).toBeVisible();
    expect(screen.getByRole("button", { name: "Publish version" })).toBeDisabled();
    expect(publish).not.toHaveBeenCalled();
  });

  it("allows publishing once the save lands and the draft is clean", async () => {
    // Once `markSaved` clears `isDirty`, the server draft equals the canvas, so the
    // publish is allowed and carries the revision the save advanced to.
    seed(VALID_GRAPH, 2);
    act(() => useWorkflowEditorStore.getState().markDirty());
    const publish = vi.fn().mockResolvedValue(publishedVersion());
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    expect(screen.getByRole("button", { name: /Publish/ })).toBeDisabled();

    act(() => useWorkflowEditorStore.getState().markSaved(3));
    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Publish version" }));

    await waitFor(() => expect(publish).toHaveBeenCalledWith({ note: null, expected_revision: 3 }));
  });

  it("keeps the confirm blocked by client validation even when the draft is clean", async () => {
    // The save-gate does not weaken the existing validation gate: an invalid graph
    // stays blocked whether or not it is persisted.
    seed(EMPTY_GRAPH, 0);
    const publish = vi.fn();
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={publish} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));

    expect(screen.getByText("Fix the problems below before publishing.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Publish version" })).toBeDisabled();
    expect(publish).not.toHaveBeenCalled();
  });

  it("can be dismissed with Cancel", async () => {
    seed(VALID_GRAPH, 0);
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
