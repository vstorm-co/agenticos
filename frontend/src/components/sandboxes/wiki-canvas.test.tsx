import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WikiCanvas } from "./wiki-canvas";
import { layoutWiki } from "@/lib/wiki-layout";
import { buildWikiGraph, parseWikiPage } from "@/lib/wiki-graph";
import type { WikiFlowNode } from "@/lib/wiki-flow";
import type { ReactFlowProps } from "@xyflow/react";

vi.mock("@/lib/wiki-layout", async (original) => {
  const actual = await original<typeof import("@/lib/wiki-layout")>();
  return { ...actual, layoutWiki: vi.fn(actual.layoutWiki) };
});

vi.mock("@/hooks/use-resolved-theme", () => ({ useResolvedTheme: () => "light" }));
vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  ReactFlow: ({ nodes, onNodesChange }: ReactFlowProps<WikiFlowNode>) => (
    <div>
      <output aria-label="Measurements">{JSON.stringify(nodes?.[0]?.measured)}</output>
      <button
        onClick={() =>
          onNodesChange?.([
            { id: "a.md", type: "dimensions", dimensions: { width: 20, height: 20 } },
          ])
        }
      >
        Measure note
      </button>
      <output aria-label="Position">{JSON.stringify(nodes?.[0]?.position)}</output>
      <button
        onClick={() =>
          onNodesChange?.([{ id: "a.md", type: "position", position: { x: 120, y: 240 } }])
        }
      >
        Drag note
      </button>
      <button onClick={() => onNodesChange?.([{ id: "a.md", type: "select", selected: true }])}>
        Select with keyboard
      </button>
      <button
        onClick={() =>
          onNodesChange?.([
            { id: "a.md", type: "select", selected: false },
            { id: "a.md", type: "position" },
          ])
        }
      >
        Finish movement
      </button>
    </div>
  ),
}));

it("keeps a dragged point's position when selection and refreshed graph data change", () => {
  const graph = buildWikiGraph([parseWikiPage("a.md", "# A")]);
  const onSelect = vi.fn();
  const { rerender } = render(
    <WikiCanvas graph={graph} visible={new Set(["a.md"])} selected={null} onSelect={onSelect} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Measure note" }));
  expect(screen.getByLabelText("Measurements")).toHaveTextContent('{"width":20,"height":20}');
  fireEvent.click(screen.getByRole("button", { name: "Drag note" }));
  expect(screen.getByLabelText("Position")).toHaveTextContent('{"x":120,"y":240}');
  fireEvent.click(screen.getByRole("button", { name: "Select with keyboard" }));
  expect(onSelect).toHaveBeenCalledWith("a.md");
  fireEvent.click(screen.getByRole("button", { name: "Finish movement" }));
  rerender(
    <WikiCanvas
      graph={buildWikiGraph([parseWikiPage("a.md", "# Updated")])}
      visible={new Set(["a.md"])}
      selected="a.md"
      onSelect={onSelect}
    />,
  );
  expect(screen.getByLabelText("Position")).toHaveTextContent('{"x":120,"y":240}');
  expect(screen.getByLabelText("Measurements")).toHaveTextContent('{"width":20,"height":20}');
  expect(onSelect).toHaveBeenCalledTimes(1);
});

it("reuses physics for selection and filtering, and recomputes it only for new graph data", () => {
  vi.mocked(layoutWiki).mockClear();
  const graph = buildWikiGraph([parseWikiPage("a.md", "[[b]]"), parseWikiPage("b.md", "")]);
  const onSelect = vi.fn();
  const { rerender } = render(
    <WikiCanvas
      graph={graph}
      selected={null}
      visible={new Set(["a.md", "b.md"])}
      onSelect={onSelect}
    />,
  );
  expect(layoutWiki).toHaveBeenCalledTimes(1);
  rerender(
    <WikiCanvas graph={graph} selected="a.md" visible={new Set(["a.md"])} onSelect={onSelect} />,
  );
  expect(layoutWiki).toHaveBeenCalledTimes(1);
  rerender(
    <WikiCanvas
      graph={{ ...graph }}
      selected="a.md"
      visible={new Set(["a.md"])}
      onSelect={onSelect}
    />,
  );
  expect(layoutWiki).toHaveBeenCalledTimes(2);
});
