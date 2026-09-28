import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ValidationProblem } from "@/components/workflows/validation";
import type { EditorSelection } from "@/stores/workflow-editor-store";
import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import {
  DEBUG_ECHO,
  echo,
  edge,
  graph,
  makeCatalog,
  node,
} from "@/components/workflows/validation/fixtures";

import { PanelShell } from "./panel-shell";

const catalog = makeCatalog([DEBUG_ECHO]);
const NO_SELECTION: EditorSelection = { nodeIds: [], edgeIds: [] };

function mount(
  options: {
    graph?: WorkflowGraph | null;
    selectedNode?: NodeInstance | null;
    selection?: EditorSelection;
    problems?: ValidationProblem[];
    onDeleteNodes?: (ids: string[]) => void;
  } = {},
) {
  const onSelectNode = vi.fn();
  render(
    <PanelShell
      graph={
        options.graph === undefined ? graph({ entry: "A", nodes: [echo("A")] }) : options.graph
      }
      selectedNode={options.selectedNode ?? null}
      selection={options.selection ?? NO_SELECTION}
      catalog={catalog}
      problems={options.problems ?? []}
      updateNodeConfig={vi.fn()}
      upsertBinding={vi.fn()}
      removeBinding={vi.fn()}
      onSelectNode={onSelectNode}
      onDeleteNodes={options.onDeleteNodes}
    />,
  );
  return { onSelectNode };
}

describe("PanelShell states", () => {
  it("shows the empty state before a graph loads", () => {
    mount({ graph: null });
    expect(screen.getByText("Select a node to edit it.")).toBeVisible();
  });

  it("shows the empty state with a problems footer when nothing is selected", () => {
    mount({
      problems: [{ nodeId: "A", edgeId: null, field: null, code: "c", message: "Graph problem" }],
    });
    expect(screen.getByText("Select a node to edit it.")).toBeVisible();
    expect(screen.getByRole("button", { name: "1 problem" })).toBeVisible();
  });

  it("shows a multi-selection with a bulk-delete affordance when wired", async () => {
    const onDeleteNodes = vi.fn();
    mount({ selection: { nodeIds: ["A", "B"], edgeIds: [] }, onDeleteNodes });
    expect(screen.getByText("2 nodes selected")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(onDeleteNodes).toHaveBeenCalledWith(["A", "B"]);
  });

  it("omits the bulk-delete button when the host does not wire it", () => {
    mount({ selection: { nodeIds: ["A", "B"], edgeIds: [] } });
    expect(screen.queryByRole("button", { name: "Delete selected" })).toBeNull();
  });

  it("renders the form for a single selected node with its problems", () => {
    const selectedNode = echo("A");
    mount({
      graph: graph({ entry: "A", nodes: [selectedNode] }),
      selectedNode,
      selection: { nodeIds: ["A"], edgeIds: [] },
      problems: [{ nodeId: "A", edgeId: null, field: null, code: "c", message: "Node problem" }],
    });
    expect(screen.getByRole("heading", { name: "Echo · A" })).toBeVisible();
    expect(screen.getByText("Configuration")).toBeVisible();
    expect(screen.getByText("Node problem")).toBeVisible();
    expect(screen.getByLabelText("1 problem")).toBeVisible();
  });

  it("says so when a selected node's definition is unknown", () => {
    const selectedNode = node("Z", "missing");
    mount({
      graph: graph({ entry: "Z", nodes: [selectedNode] }),
      selectedNode,
      selection: { nodeIds: ["Z"], edgeIds: [] },
    });
    expect(screen.getByText("This node's type is not in the catalog.")).toBeVisible();
  });

  it("falls through to empty when one node is selected but not resolved", () => {
    mount({ selection: { nodeIds: ["A"], edgeIds: [] }, selectedNode: null });
    expect(screen.getByText("Select a node to edit it.")).toBeVisible();
  });

  it("renders an edge panel, labelling a known, an unknown and a dangling endpoint", () => {
    mount({
      graph: graph({
        entry: "A",
        nodes: [echo("A"), node("U", "missing")],
        edges: [edge("e", "U", "out", "gonenode", "in")],
      }),
      selection: { nodeIds: [], edgeIds: ["e"] },
    });
    expect(screen.getByText("Connection")).toBeVisible();
    // A present node with an unknown definition falls back to its definition id.
    expect(screen.getByText(/missing · U/)).toBeVisible();
    // A dangling endpoint falls back to a short id.
    expect(screen.getByText(/goneno/)).toBeVisible();
  });

  it("labels a known edge endpoint by its catalog name", () => {
    const a = echo("A");
    mount({
      graph: graph({
        entry: "A",
        nodes: [a, echo("B")],
        edges: [edge("e", "A", "out", "B", "in")],
      }),
      selection: { nodeIds: [], edgeIds: ["e"] },
    });
    expect(screen.getByText(/Echo · A/)).toBeVisible();
  });

  it("falls through to empty when the selected edge is not found", () => {
    mount({ selection: { nodeIds: [], edgeIds: ["nope"] } });
    expect(screen.getByText("Select a node to edit it.")).toBeVisible();
  });
});
