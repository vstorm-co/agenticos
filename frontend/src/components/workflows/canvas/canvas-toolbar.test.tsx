import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEBUG_ECHO, makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance, WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";

import { copyToClipboard } from "./use-canvas-shortcuts";
import { WorkflowCanvas } from "./workflow-canvas";

vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => ({ connections: null, canConnect: false }),
  useMcpAppStep: () => null,
}));

// Adding a step reads the channel bots to start a reply wired; none are known here.
vi.mock("@/hooks/use-permissions", async (original) => ({
  ...(await original<typeof import("@/hooks/use-permissions")>()),
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("@/hooks/use-channel-bots", async (original) => ({
  ...(await original<typeof import("@/hooks/use-channel-bots")>()),
  useChannelBots: () => ({ bots: [], isLoading: false, error: null }),
}));

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

/** An element's text as a screen reader gets it: what is hidden from it left out. */
function heard(element: Element | null | undefined): string {
  const copy = element?.cloneNode(true) as Element | undefined;
  copy?.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
  return (copy?.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("the canvas toolbar", () => {
  it("adds a step from Add step, and opens the settings of one that has any", async () => {
    seed(node("a"));
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.getByText("No problems")).toBeTruthy();

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

    // The toolbar's list, not a step's own marker: the one that opens a list.
    const pill = screen
      .getAllByRole("button", { name: /Finish setup/ })
      .find((button) => button.getAttribute("aria-haspopup") === "dialog");
    await userEvent.click(pill as HTMLElement);
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
    expect(screen.queryByText("No problems")).toBeNull();
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
  it("opens its settings when double-clicked", () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    fireEvent.dblClick(container.querySelector(".react-flow__node") as HTMLElement);
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
    await userEvent.click(await screen.findByRole("button", { name: "Paste" }));
    expect(store.getState().graph?.nodes).toHaveLength(2);
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();
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

  it("switches a step off and on, and never the trigger", async () => {
    seed(node("a"), node("b", "act.one", 300));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const card = container.querySelector('[data-node-id="b"]') as HTMLElement;

    fireEvent.contextMenu(card);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Switch off/ }));
    expect(store.getState().graph?.nodes.find((item) => item.id === "b")?.disabled).toBe(true);

    fireEvent.contextMenu(card);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Switch on/ }));
    expect(store.getState().graph?.nodes.find((item) => item.id === "b")?.disabled).toBe(false);

    fireEvent.contextMenu(container.querySelector('[data-node-id="a"]') as HTMLElement);
    await screen.findByRole("menuitem", { name: /Open settings/ });
    expect(screen.queryByRole("menuitem", { name: /Switch off/ })).toBeNull();
  });

  it("opens the step picker where the canvas was right-clicked, and adds the step there", async () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const pane = container.querySelector('[data-workflow-region="canvas"]') as HTMLElement;

    fireEvent.contextMenu(pane, { clientX: 200, clientY: 120 });
    expect(await screen.findByPlaceholderText("Search steps")).toBeTruthy();
    // Nothing copied, so nothing to paste; no step menu either.
    expect(screen.queryByRole("button", { name: "Paste" })).toBeNull();
    expect(screen.queryByRole("menuitem")).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /Act/ }));

    expect(store.getState().graph?.nodes).toHaveLength(2);
    await waitFor(() => expect(screen.queryByPlaceholderText("Search steps")).toBeNull());
  });

  it("opens nothing at the end of a right-button drag, which pans the canvas", () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const pane = container.querySelector('[data-workflow-region="canvas"]') as HTMLElement;

    fireEvent.mouseDown(pane, { button: 2, clientX: 100, clientY: 100 });
    fireEvent.contextMenu(pane, { clientX: 180, clientY: 140 });
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();

    // A drag that ends on a step opens no step menu either.
    const card = container.querySelector('[data-node-id="a"]') as HTMLElement;
    fireEvent.mouseDown(pane, { button: 2, clientX: 100, clientY: 100 });
    fireEvent.contextMenu(card, { clientX: 160, clientY: 100 });
    expect(screen.queryByRole("menuitem")).toBeNull();
  });

  // jsdom has no PointerEvent; React reads the button and position off any event typed pointerup.
  const release = (target: HTMLElement, button: number, clientX: number, clientY: number) =>
    act(() => {
      target.dispatchEvent(
        new MouseEvent("pointerup", { bubbles: true, button, clientX, clientY }),
      );
    });

  it("waits for the release where the menu comes on the press, and opens nothing after a drag", async () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const pane = container.querySelector('[data-workflow-region="canvas"]') as HTMLElement;

    // macOS and Linux: the context menu fires while the right button is still down.
    fireEvent.mouseDown(pane, { button: 2, buttons: 2, clientX: 100, clientY: 100 });
    fireEvent.contextMenu(pane, { button: 2, buttons: 2, clientX: 100, clientY: 100 });
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();
    release(pane, 2, 190, 160);
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();

    fireEvent.mouseDown(pane, { button: 2, buttons: 2, clientX: 100, clientY: 100 });
    fireEvent.contextMenu(pane, { button: 2, buttons: 2, clientX: 100, clientY: 100 });
    release(pane, 0, 100, 100);
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();
    release(pane, 2, 101, 100);
    expect(await screen.findByPlaceholderText("Search steps")).toBeTruthy();
  });

  it("still opens the picker on a right press that stayed put", async () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const pane = container.querySelector('[data-workflow-region="canvas"]') as HTMLElement;

    fireEvent.mouseDown(pane, { button: 2, clientX: 100, clientY: 100 });
    fireEvent.contextMenu(pane, { clientX: 102, clientY: 101 });
    expect(await screen.findByPlaceholderText("Search steps")).toBeTruthy();
  });

  it("closes the picker on Escape without adding anything", async () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    fireEvent.contextMenu(
      container.querySelector('[data-workflow-region="canvas"]') as HTMLElement,
    );
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByPlaceholderText("Search steps")).toBeNull());
    expect(store.getState().graph?.nodes).toHaveLength(1);
  });

  it("opens no picker on a canvas that cannot be edited", () => {
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />);
    fireEvent.contextMenu(
      container.querySelector('[data-workflow-region="canvas"]') as HTMLElement,
    );
    expect(screen.queryByPlaceholderText("Search steps")).toBeNull();
  });
});

describe("arranging and reading the canvas", () => {
  it("switches the steps between colour and Simple, for this browser", async () => {
    useWorkflowEditorStore.setState({ minimapShown: false });
    useWorkflowNodeStyleStore.setState({ style: "colour" });
    seed(node("a"));
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const tile = () => container.querySelector("[data-node-id='a'] span[data-node-family]");
    expect(tile()).toHaveClass("node-tile-data");

    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Show steps plainly" }));
    expect(useWorkflowNodeStyleStore.getState().style).toBe("simple");
    expect(tile()).toHaveClass("bg-muted");
    // The minimap follows: no family colour in Simple, the family's colour otherwise.
    const mark = () =>
      container.querySelector("rect.react-flow__minimap-node") as SVGElement | null;
    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Show the minimap" }));
    expect(container.querySelector(".react-flow__minimap")).not.toBeNull();
    expect(mark()).not.toBeNull();
    expect(mark()?.style.fill).toBe("");

    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Show steps in colour" }));
    expect(useWorkflowNodeStyleStore.getState().style).toBe("colour");
    expect(tile()).toHaveClass("node-tile-data");
    expect(mark()?.style.fill).toBe("var(--family-map-data)");
    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    expect(screen.getByRole("menuitemcheckbox", { name: "Show steps plainly" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.keyboard("{Escape}");
    expect(container.querySelector(".react-flow__minimap")).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Hide the minimap" }));
  });

  it("tidies the steps in one edit, shows a minimap and the shortcut sheet", async () => {
    useWorkflowEditorStore.setState({ minimapShown: false });
    seed(node("a", "act.one", 0), node("b", "act.one", 0));
    store.getState().applyEdgeChanges([]);
    store.setState({
      graph: {
        ...store.getState().graph!,
        edges: [
          {
            id: "e",
            source_node_id: "a",
            source_port: "out",
            target_node_id: "b",
            target_port: "in",
          },
        ],
      },
    });
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await userEvent.click(screen.getByRole("button", { name: "Tidy up" }));
    const [a, b] = store.getState().graph!.nodes;
    expect(b!.layout.x).toBeGreaterThan(a!.layout.x);

    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Show the minimap" }));
    expect(container.querySelector(".react-flow__minimap")).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: "Hide the minimap" }));
    expect(container.querySelector(".react-flow__minimap")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Canvas options" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Keyboard shortcuts" }));
    expect(screen.getByRole("heading", { name: "Keyboard shortcuts" })).toBeInTheDocument();
    // Two keys that each delete are two keys, not one label naming both.
    const deleteKey = screen.getByText("Delete", { selector: "kbd" });
    expect(deleteKey.closest("dt")?.querySelectorAll("kbd")).toHaveLength(2);
    expect(screen.getByText("Backspace", { selector: "kbd" }).closest("dt")).toBe(
      deleteKey.closest("dt"),
    );
    // Each key its own: the modifier once, then the letters it takes.
    const copy = screen.getByText("C", { selector: "kbd" }).closest("dt");
    expect(Array.from(copy?.querySelectorAll("kbd") ?? []).map((key) => key.textContent)).toEqual([
      "⌘/Ctrl",
      "C",
      "V",
      "X",
    ]);
    // "·" marks keys that each do it, "+" keys pressed together - and a screen reader hears which.
    expect(copy?.textContent).toContain("⌘/Ctrl+C·");
    expect(heard(copy)).toBe("⌘/Ctrl+C or V or X");
    expect(heard(deleteKey.closest("dt"))).toBe("Delete or Backspace");
    await userEvent.keyboard("{Escape}");
    expect(store.getState().overlay).toBeNull();
  });

  it("puts a step picked after a connection's + into that connection", async () => {
    seed(node("a", "act.one", 0), node("b", "act.one", 600));
    store.setState({
      graph: {
        ...store.getState().graph!,
        edges: [
          {
            id: "e",
            source_node_id: "a",
            source_port: "out",
            target_node_id: "b",
            target_port: "in",
          },
        ],
      },
    });
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    act(() => store.getState().beginSplit("e"));
    await userEvent.click(await screen.findByRole("option", { name: /Act/ }));

    const edges = store.getState().graph!.edges;
    expect(edges.some((item) => item.id === "e")).toBe(false);
    expect(edges.map((item) => [item.source_node_id, item.target_node_id])).toContainEqual([
      "a",
      store.getState().graph!.nodes[2]!.id,
    ]);
    expect(store.getState().splitEdgeId).toBeNull();
  });
});
