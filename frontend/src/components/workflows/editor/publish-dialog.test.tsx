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
    graph: VALID_GRAPH,
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

  it("can be dismissed with Cancel", async () => {
    seed(VALID_GRAPH, 0);
    render(<PublishDialog catalog={[DEBUG_ECHO]} publish={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
