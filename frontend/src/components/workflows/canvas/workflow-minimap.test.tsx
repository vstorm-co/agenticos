import { fireEvent, render } from "@testing-library/react";
import { ReactFlow, ReactFlowProvider, type Edge, type Node } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";
import { WorkflowMinimap, minimapWires } from "./workflow-minimap";

const flow = vi.hoisted(() => ({ setCenter: vi.fn(), zoom: 1.5 }));
vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  useReactFlow: () => ({ setCenter: flow.setCenter, getZoom: () => flow.zoom }),
}));

const nodes: Node[] = [
  { id: "a", position: { x: 0, y: 10 }, data: {}, measured: { width: 240, height: 80 } },
  { id: "b", position: { x: 400, y: 150 }, data: {}, initialWidth: 240, initialHeight: 100 },
  { id: "c", position: { x: 400, y: -100 }, data: {}, hidden: true },
];
const edges: Edge[] = [{ id: "ab", source: "a", target: "b" }];

describe("workflow overview wires", () => {
  it("follows the actual layout and measured card sizes while moving or resizing", () => {
    const path = minimapWires(nodes, edges).get("b")?.[0];
    expect(path).toMatch(/^M240,50/);
    expect(path).toMatch(/400,200$/);
    const resized = nodes.map((node) =>
      node.id === "a"
        ? { ...node, position: { x: 30, y: 60 }, measured: { width: 300, height: 120 } }
        : node,
    );
    expect(minimapWires(resized, edges).get("b")?.[0]).toMatch(/^M330,120/);
  });

  it("keeps branches but excludes hidden edges, hidden nodes and dangling connections", () => {
    const wires = minimapWires(nodes, [
      ...edges,
      { id: "second", source: "b", target: "a" },
      { id: "hidden-edge", source: "a", target: "b", hidden: true },
      { id: "hidden-node", source: "a", target: "c" },
      { id: "missing", source: "missing", target: "b" },
    ]);
    expect(wires.get("b")).toHaveLength(1);
    expect(wires.get("a")).toHaveLength(1);
    expect(wires.has("c")).toBe(false);
  });
});

describe("the overview map", () => {
  it("draws every step and centres the canvas where the map is clicked, keeping the zoom", () => {
    const shown: Node[] = [
      { id: "a", position: { x: 0, y: 0 }, data: {}, width: 240, height: 80 },
      { id: "n", type: "note", position: { x: 0, y: 200 }, data: {}, width: 240, height: 80 },
      { id: "t", type: "trigger", position: { x: 300, y: 0 }, data: {}, width: 240, height: 80 },
    ];
    const { container, getByTestId } = render(
      <ReactFlowProvider>
        <ReactFlow nodes={shown} edges={[{ id: "at", source: "a", target: "t" }]}>
          <WorkflowMinimap />
        </ReactFlow>
      </ReactFlowProvider>,
    );

    expect(container.querySelectorAll(".react-flow__minimap-node")).toHaveLength(3);
    fireEvent.click(getByTestId("rf__minimap").querySelector("svg") as SVGElement);

    expect(flow.setCenter).toHaveBeenCalledWith(expect.any(Number), expect.any(Number), {
      zoom: 1.5,
    });
  });
});
