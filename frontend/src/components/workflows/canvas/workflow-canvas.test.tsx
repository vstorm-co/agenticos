import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { NodeDefinition, WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NODE_DRAG_MIME } from "@/components/workflows/palette";

import { ERROR_PORT_ID } from "./graph-adapter";
import { WorkflowCanvas } from "./workflow-canvas";

const store = useWorkflowEditorStore;

/** A minimal `DataTransfer` carrying (or not) a palette node payload. */
function dragData(payload?: NodeDefinition): DataTransfer {
  return {
    dropEffect: "",
    getData: (type: string) => (payload && type === NODE_DRAG_MIME ? JSON.stringify(payload) : ""),
  } as unknown as DataTransfer;
}

function def(overrides: Partial<NodeDefinition>): NodeDefinition {
  return {
    id: "act",
    version: 1,
    name: "Act",
    category: "c",
    description: "",
    kind: "action",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: [
      { id: "in", label: "In", kind: "input", schema: null },
      { id: "out", label: "Out", kind: "output", schema: null },
    ],
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
    ...overrides,
  };
}

const ACTION = def({ id: "act", name: "Act" });
const CONTROL = def({
  id: "ctrl",
  name: "Ctrl",
  kind: "control",
  ports: [
    { id: "in", label: "In", kind: "input", schema: null },
    { id: "then", label: "Then", kind: "output", schema: null },
    { id: ERROR_PORT_ID, label: "Error", kind: "output", schema: null },
  ],
});
const WAITING = def({ id: "wait", name: "Wait", kind: "waiting" });
const CATALOG = [ACTION, CONTROL, WAITING];

function node(id: string, definitionId: string, version = 1) {
  return {
    id,
    definition_id: definitionId,
    definition_version: version,
    config: {},
    layout: { x: 0, y: 0 },
  };
}

function workflow(): WorkflowDetail {
  return {
    id: "wf-1",
    slug: "wf",
    name: "WF",
    description: null,
    status: "draft",
    visibility: "private",
    owner_user_id: null,
    current_version_id: null,
    draft_revision: 0,
    created_at: null,
    updated_at: null,
    draft_graph: null,
  };
}

function seedFourKinds(): void {
  const graph: WorkflowGraph = {
    entry_node_id: "a",
    nodes: [node("a", "act"), node("c", "ctrl"), node("w", "wait"), node("u", "ghost", 9)],
    edges: [],
    bindings: [],
    scopes: [],
  };
  store.getState().seedGraph(graph);
}

function seedTwoActions(): void {
  store.getState().seedGraph({
    entry_node_id: "a",
    nodes: [node("a", "act"), { ...node("b", "act"), layout: { x: 240, y: 0 } }],
    edges: [],
    bindings: [],
    scopes: [],
  });
}

function seedTwoConnected(): void {
  store.getState().seedGraph({
    entry_node_id: "a",
    nodes: [node("a", "act"), { ...node("b", "act"), layout: { x: 240, y: 0 } }],
    edges: [
      { id: "e1", source_node_id: "a", source_port: "out", target_node_id: "b", target_port: "in" },
    ],
    bindings: [],
    scopes: [],
  });
}

function seedControlAndAction(): void {
  store.getState().seedGraph({
    entry_node_id: "c",
    nodes: [node("c", "ctrl"), { ...node("b", "act"), layout: { x: 240, y: 0 } }],
    edges: [],
    bindings: [],
    scopes: [],
  });
}

describe("WorkflowCanvas", () => {
  beforeEach(() => {
    store.getState().teardown();
  });

  it("renders the canvas region and a card for every node, known or not", () => {
    seedFourKinds();
    const { container, getByText } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} />,
    );

    expect(container.querySelector('[data-workflow-region="canvas"]')).toBeTruthy();
    expect(getByText("Act")).toBeTruthy();
    expect(getByText("Ctrl")).toBeTruthy();
    expect(getByText("Wait")).toBeTruthy();
    // An unknown definition falls back to its id and draws no handles of its own.
    expect(getByText("ghost")).toBeTruthy();
    expect(container.querySelector('[data-node-id="u"] .react-flow__handle')).toBeNull();
  });

  it("draws a distinct handle for the error output port", () => {
    seedFourKinds();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    expect(container.querySelectorAll(".react-flow__handle").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-node-id="c"] [data-port-variant="error"]')).toBeTruthy();
  });

  it("connects two nodes through the keyboard connect mode", async () => {
    seedTwoActions();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    const region = container.querySelector('[data-workflow-region="canvas"]');
    expect(region?.getAttribute("data-connecting")).toBe("false");

    fireEvent.click(container.querySelector('[data-node-id="a"] button[aria-label^="Start"]')!);
    expect(region?.getAttribute("data-connecting")).toBe("true");

    await waitFor(() =>
      expect(
        container.querySelector('[data-node-id="b"] button[aria-label^="Complete"]'),
      ).toBeTruthy(),
    );
    fireEvent.click(container.querySelector('[data-node-id="b"] button[aria-label^="Complete"]')!);

    await waitFor(() => expect(store.getState().graph?.edges).toHaveLength(1));
    expect(store.getState().graph?.edges[0]).toMatchObject({
      source_node_id: "a",
      source_port: "out",
      target_node_id: "b",
      target_port: "in",
    });
    expect(region?.getAttribute("data-connecting")).toBe("false");
  });

  it("refuses to complete an incompatible connection", async () => {
    const producer = def({
      id: "producer",
      name: "Producer",
      ports: [
        {
          id: "out",
          label: "Out",
          kind: "output",
          schema: { type: "object", title: "A", properties: { a: { type: "string" } } },
        },
      ],
    });
    const consumer = def({
      id: "consumer",
      name: "Consumer",
      ports: [
        {
          id: "in",
          label: "In",
          kind: "input",
          schema: { type: "object", title: "B", properties: { b: { type: "string" } } },
        },
      ],
    });
    store.getState().seedGraph({
      entry_node_id: "p",
      nodes: [node("p", "producer"), { ...node("q", "consumer"), layout: { x: 240, y: 0 } }],
      edges: [],
      bindings: [],
      scopes: [],
    });
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={[producer, consumer]} />,
    );

    fireEvent.click(container.querySelector('[data-node-id="p"] button[aria-label^="Start"]')!);
    await waitFor(() =>
      expect(
        container.querySelector('[data-node-id="q"] button[aria-label^="Complete"]'),
      ).toBeTruthy(),
    );
    fireEvent.click(container.querySelector('[data-node-id="q"] button[aria-label^="Complete"]')!);

    expect(store.getState().graph?.edges).toHaveLength(0);
    expect(
      container.querySelector('[data-workflow-region="canvas"]')?.getAttribute("data-connecting"),
    ).toBe("false");
  });

  it("leaves connect mode on Escape without adding an edge", () => {
    seedTwoActions();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    const region = container.querySelector('[data-workflow-region="canvas"]')!;

    fireEvent.click(container.querySelector('[data-node-id="a"] button[aria-label^="Start"]')!);
    expect(region.getAttribute("data-connecting")).toBe("true");

    fireEvent.keyDown(region, { key: "Escape" });
    expect(region.getAttribute("data-connecting")).toBe("false");
    expect(store.getState().graph?.edges).toHaveLength(0);
  });

  it("renders read-only with non-interactive handles and no connect controls", () => {
    seedTwoActions();
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} readOnly />,
    );
    // Handles still mount so xyflow can position edges (error 008 otherwise), but
    // are made non-interactive — pointer events off and not connectable.
    const handles = container.querySelectorAll(".react-flow__handle");
    expect(handles.length).toBeGreaterThan(0);
    handles.forEach((handle) => expect(handle.className).toContain("pointer-events-none"));
    // The keyboard connect controls are gone in read-only.
    expect(container.querySelector('button[aria-label^="Start"]')).toBeNull();
    expect(container.querySelector('button[aria-label^="Complete"]')).toBeNull();
  });

  it("keeps a read-only edge's ports handled, so xyflow can anchor it", () => {
    seedTwoConnected();
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} readOnly />,
    );
    // The regression: with the source/target handles unmounted in read-only,
    // xyflow's getEdgePosition returned null and the edge vanished (error 008).
    // Both referenced port handles must still mount (jsdom lays out no SVG, so the
    // rendered edge path itself is not assertable here — the handles are).
    const source = container.querySelector('[data-node-id="a"] [data-port-variant="output"]');
    const target = container.querySelector('[data-node-id="b"] [data-port-variant="input"]');
    expect(source).toBeTruthy();
    expect(target).toBeTruthy();
    // And they are non-interactive, matching the published view.
    expect(source?.className).toContain("pointer-events-none");
    expect(container.querySelector(".react-flow__edges")).toBeTruthy();
  });

  it("ignores Backspace and Delete when read-only", () => {
    seedTwoConnected();
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} readOnly />,
    );
    const region = container.querySelector('[data-workflow-region="canvas"]')!;
    // Even with a node selected in the store, a published view must not delete:
    // `deleteKeyCode` is null and elements are not selectable.
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });

    fireEvent.keyDown(region, { key: "Backspace" });
    fireEvent.keyDown(region, { key: "Delete" });

    expect(store.getState().graph?.nodes).toHaveLength(2);
    expect(store.getState().graph?.edges).toHaveLength(1);
    expect(store.getState().isDirty).toBe(false);
  });

  it("starts a keyboard connection from a control node's error port, not just the first", async () => {
    seedControlAndAction();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    // Each output port gets its own Start button — the error and branch outputs a
    // mouse user could reach are now reachable by keyboard too.
    expect(
      container.querySelectorAll('[data-node-id="c"] button[aria-label^="Start"]'),
    ).toHaveLength(2);
    const errorStart = container.querySelector(
      '[data-node-id="c"] button[aria-label$="port Error"]',
    );
    expect(errorStart).toBeTruthy();

    fireEvent.click(errorStart!);
    await waitFor(() =>
      expect(
        container.querySelector('[data-node-id="b"] button[aria-label^="Complete"]'),
      ).toBeTruthy(),
    );
    fireEvent.click(container.querySelector('[data-node-id="b"] button[aria-label^="Complete"]')!);

    await waitFor(() => expect(store.getState().graph?.edges).toHaveLength(1));
    expect(store.getState().graph?.edges[0]).toMatchObject({
      source_node_id: "c",
      source_port: "error",
      target_node_id: "b",
      target_port: "in",
    });
  });

  it("shows the empty-canvas hint before the store has a graph", () => {
    const { container, queryByText, getByText } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} />,
    );
    expect(container.querySelector('[data-workflow-region="canvas"]')).toBeTruthy();
    expect(queryByText("Act")).toBeNull();
    expect(getByText("Your workflow's steps and connections appear here.")).toBeTruthy();
  });

  it("adds a node dropped from the palette at the drop point", () => {
    seedTwoActions();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    const region = container.querySelector('[data-workflow-region="canvas"]')!;

    expect(fireEvent.dragOver(region, { dataTransfer: dragData(ACTION) })).toBe(false);
    fireEvent.drop(region, { dataTransfer: dragData(ACTION) });

    expect(store.getState().graph?.nodes).toHaveLength(3);
    expect(store.getState().graph?.nodes.at(-1)?.definition_id).toBe("act");
  });

  it("ignores a drop that carries no palette payload", () => {
    seedTwoActions();
    const { container } = render(<WorkflowCanvas workflow={workflow()} catalog={CATALOG} />);
    const region = container.querySelector('[data-workflow-region="canvas"]')!;

    fireEvent.drop(region, { dataTransfer: dragData() });
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("does not accept a drop when read-only", () => {
    seedTwoActions();
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} readOnly />,
    );
    const region = container.querySelector('[data-workflow-region="canvas"]')!;

    // Read-only leaves the drag uncancelled and adds nothing.
    expect(fireEvent.dragOver(region, { dataTransfer: dragData(ACTION) })).toBe(true);
    fireEvent.drop(region, { dataTransfer: dragData(ACTION) });
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });
});
