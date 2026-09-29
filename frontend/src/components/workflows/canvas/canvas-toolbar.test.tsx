import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DEBUG_ECHO, makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance, WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { copyToClipboard } from "./use-canvas-shortcuts";
import { WorkflowCanvas } from "./workflow-canvas";

const store = useWorkflowEditorStore;

const IO = [port("in", "input", null), port("out", "output", null)];
const ACT = makeDefinition({ id: "act.one", name: "Act", category: "data", ports: IO });
const MERGE = makeDefinition({ id: "logic.merge", name: "Merge", category: "logic", ports: IO });
// A step with settings, in a group the picker shows.
const SET = makeDefinition({
  id: "act.set",
  name: "Set",
  category: "files",
  config_schema: DEBUG_ECHO.config_schema,
  ports: IO,
});
const CATALOG = [ACT, MERGE, SET];

const WORKFLOW = {
  id: "wf",
  draft_graph: null,
} as unknown as WorkflowDetail;

function node(id: string, definitionId = "act.one", x = 0): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: 1,
    config: {},
    layout: { x, y: 0 },
  };
}

function seed(...nodes: NodeInstance[]) {
  store.getState().seedGraph({
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  });
}

afterEach(() => store.getState().teardown());

describe("the canvas toolbar", () => {
  it("adds a step from Add step, and opens the settings of one that has any", async () => {
    seed(node("a"));
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("Ready to publish")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Add step" }));
    await userEvent.click(await screen.findByRole("option", { name: /Merge/ }));
    expect(store.getState().graph?.nodes.map((item) => item.definition_id)).toEqual([
      "act.one",
      "logic.merge",
    ]);
    // Nothing to set on a merge: its settings stay closed.
    expect(store.getState().editingNodeId).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Add step" }));
    await userEvent.click(await screen.findByRole("option", { name: /Set/ }));
    const added = store.getState().graph?.nodes.at(-1);
    expect(added?.definition_id).toBe("act.set");
    expect(store.getState().editingNodeId).toBe(added?.id);
  });

  it("lists what stops a publish, and opens the step a problem is about", async () => {
    seed(node("a"), node("u", "gone.step", 300));
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await userEvent.click(screen.getByRole("button", { name: /problem/ }));
    const [first] = await screen.findAllByRole("button", { name: /gone.step/ });
    await userEvent.click(first as HTMLElement);
    expect(store.getState().editingNodeId).toBe("u");
    expect(store.getState().selection.nodeIds).toEqual(["u"]);
  });

  it("deletes a multi-selection from its bar, and shows none of it read-only", async () => {
    seed(node("a"), node("b", "act.one", 300));
    store.getState().setSelection({ nodeIds: ["a", "b"], edgeIds: [] });
    const { unmount } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(store.getState().graph?.nodes).toEqual([]);
    unmount();

    seed(node("a"));
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />);
    expect(screen.queryByRole("button", { name: "Add step" })).toBeNull();
    expect(screen.queryByText("Ready to publish")).toBeNull();
  });
});

describe("an empty canvas", () => {
  it("offers Add step in its middle", async () => {
    seed();
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByRole("button", { name: "Add step" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Add step" }));
    await userEvent.click(await screen.findByRole("option", { name: /Merge/ }));
    expect(store.getState().graph?.nodes).toHaveLength(1);
  });
});

describe("a step on the canvas", () => {
  it("opens its settings when clicked", () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    fireEvent.click(container.querySelector(".react-flow__node") as HTMLElement);
    expect(store.getState().editingNodeId).toBe("a");
  });
});

describe("the canvas menu", () => {
  it("pastes what was copied where the canvas was right-clicked", async () => {
    seed(node("a"));
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    copyToClipboard(store.getState());
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    fireEvent.contextMenu(
      container.querySelector('[data-workflow-region="canvas"]') as HTMLElement,
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: /Paste/ }));
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("acts on the step that was right-clicked", async () => {
    seed(node("a"), node("b", "act.one", 300));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const card = container.querySelector('[data-node-id="b"]') as HTMLElement;

    fireEvent.contextMenu(card);
    expect(store.getState().selection.nodeIds).toEqual(["b"]);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Open settings/ }));
    expect(store.getState().editingNodeId).toBe("b");
    store.getState().editNode(null);

    fireEvent.contextMenu(card);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Duplicate/ }));
    expect(store.getState().graph?.nodes).toHaveLength(3);

    fireEvent.contextMenu(container.querySelector('[data-node-id="a"]') as HTMLElement);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Delete step/ }));
    await waitFor(() =>
      expect(store.getState().graph?.nodes.some((item) => item.id === "a")).toBe(false),
    );
  });

  it("adds a step where the canvas was right-clicked, and undoes it", async () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const pane = container.querySelector('[data-workflow-region="canvas"]') as HTMLElement;

    fireEvent.contextMenu(pane, { clientX: 200, clientY: 120 });
    expect(await screen.findByText("Add a step here")).toBeTruthy();
    const data = screen.getByRole("menuitem", { name: "Data" });
    fireEvent.keyDown(data, { key: "ArrowRight" });
    await userEvent.click(await screen.findByRole("menuitem", { name: /Act/ }));
    expect(store.getState().graph?.nodes).toHaveLength(2);

    fireEvent.contextMenu(pane);
    expect(screen.getByRole("menuitem", { name: /Paste/ })).toHaveAttribute("data-disabled");
    await userEvent.click(screen.getByRole("menuitem", { name: /Undo/ }));
    expect(store.getState().graph?.nodes).toHaveLength(1);

    fireEvent.contextMenu(pane);
    await userEvent.click(screen.getByRole("menuitem", { name: /Redo/ }));
    expect(store.getState().graph?.nodes).toHaveLength(2);

    fireEvent.contextMenu(pane);
    await userEvent.click(screen.getByRole("menuitem", { name: /Fit to view/ }));
  });
});
