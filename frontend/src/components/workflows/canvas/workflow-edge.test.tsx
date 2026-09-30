import { fireEvent, render } from "@testing-library/react";
import { Position } from "@xyflow/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WorkflowEdge } from "./workflow-edge";
import type { WorkflowEdgeData } from "./graph-adapter";

/** Render the custom edge inside an `<svg>`, the layer `@xyflow/react` gives it. */
function renderEdge(data: WorkflowEdgeData | undefined, selected = false) {
  return render(
    <svg>
      <WorkflowEdge
        id="e1"
        source="a"
        target="b"
        sourceX={0}
        sourceY={0}
        targetX={100}
        targetY={100}
        sourcePosition={Position.Right}
        targetPosition={Position.Left}
        selected={selected}
        data={data}
      />
    </svg>,
  );
}

describe("WorkflowEdge", () => {
  it("strokes a data edge and draws no label", () => {
    const { container, queryByText } = renderEdge({ variant: "data", label: null });
    const path = container.querySelector("path");
    expect(path?.getAttribute("class")).toContain("stroke-muted-foreground");
    expect(queryByText("Then")).toBeNull();
  });

  it("strokes an error edge distinctly", () => {
    const { container } = renderEdge({ variant: "error", label: null });
    expect(container.querySelector("path")?.getAttribute("class")).toContain("stroke-destructive");
  });

  it("labels a branch edge on the wire", () => {
    const { container, getByText } = renderEdge({ variant: "branch", label: "Then" });
    expect(container.querySelector("path")?.getAttribute("class")).toContain("stroke-primary");
    expect(getByText("Then")).toBeTruthy();
  });

  it("falls back to a data edge when no variant rides along", () => {
    const { container } = renderEdge(undefined);
    expect(container.querySelector("path")?.getAttribute("class")).toContain(
      "stroke-muted-foreground",
    );
  });

  describe("deleting the connection", () => {
    const store = useWorkflowEditorStore;

    beforeEach(() => {
      store.getState().teardown();
      store.getState().seedGraph({
        entry_node_id: "a",
        nodes: ["a", "b"].map((id) => ({
          id,
          definition_id: "debug.echo",
          definition_version: 1,
          config: {},
          layout: { x: 0, y: 0 },
        })),
        edges: [
          {
            id: "e1",
            source_node_id: "a",
            source_port: "out",
            target_node_id: "b",
            target_port: "in",
          },
        ],
        bindings: [],
        scopes: [],
      });
    });

    it("offers no delete button until the edge is selected", () => {
      const { queryByRole, container } = renderEdge({ variant: "data", label: null });
      expect(queryByRole("button", { name: "Delete connection" })).toBeNull();
      expect(container.querySelector("path")?.getAttribute("style") ?? "").not.toContain("3");
    });

    it("draws a selected edge heavier and puts a delete button on it", () => {
      const { getByRole, container } = renderEdge({ variant: "data", label: null }, true);
      expect(getByRole("button", { name: "Delete connection" })).toBeTruthy();
      expect(container.querySelector("path")?.getAttribute("style")).toContain("stroke-width: 3");
    });

    it("removes the edge from the graph when the button is clicked", () => {
      const { getByRole } = renderEdge({ variant: "data", label: null }, true);
      fireEvent.click(getByRole("button", { name: "Delete connection" }));
      expect(store.getState().graph?.edges).toEqual([]);
    });

    it.each(["Enter", " "])("removes the edge on %j from the keyboard", (key) => {
      const { getByRole } = renderEdge({ variant: "data", label: null }, true);
      fireEvent.keyDown(getByRole("button", { name: "Delete connection" }), { key });
      expect(store.getState().graph?.edges).toEqual([]);
    });

    it("hands focus back to the canvas region once the edge is gone", () => {
      const region = document.createElement("div");
      region.tabIndex = -1;
      region.setAttribute("data-workflow-region", "canvas");
      document.body.appendChild(region);
      const view = render(
        <svg>
          <WorkflowEdge
            id="e1"
            source="a"
            target="b"
            sourceX={0}
            sourceY={0}
            targetX={100}
            targetY={100}
            sourcePosition={Position.Right}
            targetPosition={Position.Left}
            selected
            data={{ variant: "data", label: null }}
          />
        </svg>,
        { container: region.appendChild(document.createElement("div")) },
      );
      fireEvent.click(view.getByRole("button", { name: "Delete connection" }));
      expect(document.activeElement).toBe(region);
      view.unmount();
      region.remove();
    });

    it("ignores other keys", () => {
      const { getByRole } = renderEdge({ variant: "data", label: null }, true);
      fireEvent.keyDown(getByRole("button", { name: "Delete connection" }), { key: "a" });
      expect(store.getState().graph?.edges).toHaveLength(1);
    });

    it("moves the button below a branch label so the two do not overlap", () => {
      const plain = renderEdge({ variant: "data", label: null }, true);
      const plainAt = plain
        .getByRole("button", { name: "Delete connection" })
        .getAttribute("transform");
      plain.unmount();
      const branch = renderEdge({ variant: "branch", label: "Then" }, true);
      expect(
        branch.getByRole("button", { name: "Delete connection" }).getAttribute("transform"),
      ).not.toBe(plainAt);
    });
  });

  it("opens the step picker to put a step into a selected connection", () => {
    const edge = renderEdge({ variant: "data", label: null }, true);
    fireEvent.keyDown(edge.getByRole("button", { name: "Add a step in this connection" }), {
      key: "Enter",
    });
    expect(useWorkflowEditorStore.getState().splitEdgeId).not.toBeNull();
    expect(useWorkflowEditorStore.getState().overlay).toBe("picker");
    useWorkflowEditorStore.getState().setOverlay(null);
    expect(useWorkflowEditorStore.getState().splitEdgeId).toBeNull();

    fireEvent.click(edge.getByRole("button", { name: "Add a step in this connection" }));
    expect(useWorkflowEditorStore.getState().overlay).toBe("picker");
    fireEvent.keyDown(edge.getByRole("button", { name: "Add a step in this connection" }), {
      key: "a",
    });
  });
});
