import { render } from "@testing-library/react";
import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { WorkflowEdge } from "./workflow-edge";
import type { WorkflowEdgeData } from "./graph-adapter";

/** Render the custom edge inside an `<svg>`, the layer `@xyflow/react` gives it. */
function renderEdge(data: WorkflowEdgeData | undefined) {
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
});
