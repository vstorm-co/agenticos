import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Position, type EdgeProps, type InternalNode } from "@xyflow/react";
import { WikiEdge } from "./wiki-edge";
import { wikiFlow, type WikiFlowNode } from "@/lib/wiki-flow";
import { buildWikiGraph, parseWikiPage } from "@/lib/wiki-graph";

const state = vi.hoisted(() => ({ nodes: new Map<string, InternalNode<WikiFlowNode>>() }));
vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  useInternalNode: (id: string) => state.nodes.get(id),
}));

const props: EdgeProps = {
  id: "a-b",
  source: "a.md",
  target: "b.md",
  sourceX: 0,
  sourceY: 0,
  targetX: 0,
  targetY: 0,
  sourcePosition: Position.Right,
  targetPosition: Position.Left,
};

it("joins the dots' circumferences instead of their invisible pointer targets", () => {
  state.nodes.clear();
  const graph = buildWikiGraph([parseWikiPage("a.md", "[[b]]"), parseWikiPage("b.md", "")]);
  const view = wikiFlow(graph, new Set(["a.md", "b.md"]), null);
  for (const [index, node] of view.nodes.entries()) {
    const position = { x: index * 100, y: 0 };
    const item: InternalNode<WikiFlowNode> = {
      ...node,
      position,
      measured: { width: 20, height: 20 },
      internals: { positionAbsolute: position, z: 0, userNode: node },
    };
    state.nodes.set(node.id, item);
  }
  const { container, rerender } = render(
    <svg>
      <WikiEdge {...props} markerEnd="url(#arrow)" style={{ stroke: "red" }} />
    </svg>,
  );
  const radius = view.nodes[0]?.data.radius;
  expect(radius).toBeDefined();
  const path = container.querySelector(".react-flow__edge-path");
  expect(path).toHaveAttribute("d", `M ${10 + (radius ?? 0)},10 L ${110 - (radius ?? 0)},10`);
  expect(path).toHaveAttribute("marker-end", "url(#arrow)");
  state.nodes.delete("a.md");
  rerender(
    <svg>
      <WikiEdge {...props} />
    </svg>,
  );
  expect(container.querySelector("path")).toBeNull();
  state.nodes.clear();
  rerender(
    <svg>
      <WikiEdge {...props} source="b.md" />
    </svg>,
  );
  expect(container.querySelector("path")).toBeNull();
});
