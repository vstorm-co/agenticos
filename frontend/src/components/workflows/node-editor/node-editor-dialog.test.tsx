import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEBUG_ECHO,
  REQUIRED_INPUT,
  makeDefinition,
} from "@/components/workflows/validation/fixtures";
import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NodeEditorDialog } from "./node-editor-dialog";

vi.mock("@/hooks", () => ({ useWorkflowRuns: () => ({ start: { mutate: vi.fn() } }) }));

const store = useWorkflowEditorStore;

function node(id: string, definitionId = "debug.echo", config = {}): NodeInstance {
  return { id, definition_id: definitionId, definition_version: 1, config, layout: { x: 0, y: 0 } };
}

function seed(...nodes: NodeInstance[]) {
  const graph: WorkflowGraph = {
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  };
  store.getState().seedGraph(graph);
}

afterEach(() => store.getState().teardown());

describe("NodeEditorDialog", () => {
  it("opens nothing until a step is being edited", () => {
    seed(node("a"));
    const { container } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the step's name, what it does and its settings, and closes on Done", async () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    expect(screen.getByRole("heading", { name: "Echo" })).toBeTruthy();
    expect(screen.getByText(DEBUG_ECHO.description)).toBeTruthy();
    expect(screen.getByDisplayValue("hi")).toBeTruthy();
    expect(store.getState().selection.nodeIds).toEqual(["a"]);

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("deletes the step it shows", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete step" }));
    expect(store.getState().graph?.nodes.map((item) => item.id)).toEqual(["a"]);
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("reads without writing on a read-only editor, and says when a step's type is unknown", () => {
    seed(node("u", "gone.step"));
    store.getState().editNode("u");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} readOnly />);
    expect(screen.queryByRole("button", { name: "Delete step" })).toBeNull();
    expect(screen.getByText("This node's type is not in the catalog.")).toBeTruthy();
    // Its problem - a type nobody can publish - is said above everything else.
    expect(screen.getByLabelText(/problem/)).toBeTruthy();
  });
});

describe("a step's data", () => {
  it("sits between what the step reads and what it hands on, while editing a workflow", () => {
    seed(node("a", "debug.echo", { message: "hi" }), node("b", "debug.echo", { message: "yo" }));
    store.getState().editNode("b");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} />);

    expect(screen.getByRole("region", { name: "Input" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Output" })).toBeTruthy();
  });

  it("has no Input for the step a workflow starts from, and no data on a read-only editor", () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    const { unmount } = render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByRole("region", { name: "Input" })).toBeNull();
    expect(screen.getByRole("region", { name: "Output" })).toBeTruthy();
    unmount();

    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly />);
    expect(screen.queryByRole("region", { name: "Output" })).toBeNull();
  });
});

describe("a step's missing values", () => {
  const NEEDS = makeDefinition({ id: "test.needs", name: "Needs", input_schema: REQUIRED_INPUT });

  it("says nothing of a value not given yet until a run or a publish is tried", () => {
    seed(node("a", "test.needs"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NEEDS]} />);
    expect(screen.queryByText(/has no value yet/)).toBeNull();

    act(() => store.getState().revealProblems());

    expect(screen.getByText(/has no value yet/)).toBeInTheDocument();
  });
});

describe("a step's run policy", () => {
  it("waits behind a link until asked for, and opens at once on a step that has one", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    const { unmount } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByText("Handle errors")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "When it is slow or fails…" }));
    expect(screen.getByText("Handle errors")).toBeInTheDocument();
    unmount();

    seed(node("a"), { ...node("b"), policy: { timeout_seconds: 5 } });
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.getByText("Handle errors")).toBeInTheDocument();
  });
});
