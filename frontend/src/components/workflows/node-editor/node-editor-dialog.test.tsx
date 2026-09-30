import { act, fireEvent, render, screen } from "@testing-library/react";
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
    // Its problem - a type nobody can publish - is said under its name.
    expect(screen.getByText(/uses an unknown node: gone\.step/)).toBeTruthy();
  });
});

describe("a step's own name and whether it runs", () => {
  it("renames the step in the header, and says what kind of step a renamed one is", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    // Two Echo steps: the header tells this one apart the way the canvas does.
    await userEvent.click(screen.getByRole("button", { name: /^Echo/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Step name" }), "Say hi{Enter}");

    expect(store.getState().graph?.nodes[1]?.label).toBe("Say hi");
    expect(screen.getByRole("heading", { name: "Say hi" })).toBeTruthy();
    expect(screen.getByText(`Echo · ${DEBUG_ECHO.description}`)).toBeTruthy();
  });

  it("switches a step off in its Settings, but not the step the workflow starts from", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    const { unmount } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByRole("switch", { name: "Run this step" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    await userEvent.click(screen.getByRole("switch", { name: "Run this step" }));
    expect(store.getState().graph?.nodes[1]?.disabled).toBe(true);
    // The tab says a setting is not at its default.
    expect(screen.getByLabelText("Some settings are changed")).toBeTruthy();
    unmount();

    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.queryByRole("switch", { name: "Run this step" })).toBeNull();
    expect(screen.getByLabelText("Note")).toBeTruthy();
  });
});

describe("a step looked at in a run", () => {
  it("folds its settings away and offers nothing about slowness or failure it did not have", async () => {
    seed(node("a", "debug.echo", { message: "hi" }), node("b", "debug.echo", { message: "yo" }));
    store.getState().editNode("b");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly runData />);

    const fold = screen.getByText("Settings this step ran with");
    expect(fold.closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: /When it is slow or fails/ })).toBeNull();
    await userEvent.click(fold);
    expect(fold.closest("details")).toHaveAttribute("open");
    expect(screen.getByDisplayValue("yo")).toBeDisabled();
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
    expect(screen.queryByText(/Required: type a value/)).toBeNull();

    act(() => store.getState().revealProblems());

    expect(screen.getByText(/Required: type a value/)).toBeInTheDocument();
  });

  it("says it once its field was left, and forgets that when the dialog closes", () => {
    const NOTED = makeDefinition({
      id: "test.noted",
      name: "Noted",
      input_schema: REQUIRED_INPUT,
      config_schema: {
        type: "object",
        properties: { subject: { type: "string", title: "Subject" } },
        required: ["subject"],
      },
    });
    seed(node("a", "test.noted"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NOTED]} />);

    // Each field says it is missing once it was left, and not before.
    expect(screen.queryByText(/Required: the step cannot run/)).toBeNull();
    fireEvent.focusOut(screen.getByLabelText(/^Subject/));
    expect(screen.getByText(/Required: the step cannot run/)).toBeInTheDocument();
    expect(screen.queryByText(/Required: type a value/)).toBeNull();

    const input = document.querySelector("[data-field='value'] input") as HTMLElement;
    fireEvent.focusOut(input);
    fireEvent.focusOut(input);
    expect(screen.getByText(/Required: type a value/)).toBeInTheDocument();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    act(() => store.getState().editNode("a"));
    expect(screen.queryByText(/Required: type a value/)).toBeNull();
  });
});

describe("a step's run policy", () => {
  it("sits in the step's Settings, apart from what the step does", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    const { unmount } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByText("Handle errors")).toBeNull();
    expect(screen.queryByLabelText("Some settings are changed")).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByText("Handle errors")).toBeInTheDocument();
    unmount();

    // A step with a policy says so on the tab, before it is opened.
    seed(node("a"), { ...node("b"), policy: { timeout_seconds: 5 } });
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.getByLabelText("Some settings are changed")).toBeTruthy();
  });
});
