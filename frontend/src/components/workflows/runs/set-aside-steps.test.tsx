import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { edge, node } from "@/components/workflows/validation/fixtures";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { SetAsideSteps } from "./set-aside-steps";

const graph: WorkflowGraph = {
  entry_node_id: "entry",
  nodes: [
    node("entry", "core.input"),
    { ...node("parked", "debug.echo"), disabled: true },
    { ...node("connected", "debug.echo"), disabled: true },
    node("enabled", "debug.echo"),
  ],
  edges: [edge("e", "entry", "out", "connected", "in")],
  bindings: [],
  scopes: [],
};

it("lists and opens a parked step without inventing a node-run row", async () => {
  const inspect = vi.fn();
  render(
    <ul>
      <SetAsideSteps graph={graph} nameOf={(id) => `Step ${id}`} onInspect={inspect} />
    </ul>,
  );
  expect(screen.getByText("Switched off")).toBeVisible();
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: /Step parked/ }));
  expect(inspect).toHaveBeenCalledWith("parked");
  expect(screen.queryByText("Step connected")).not.toBeInTheDocument();
  expect(screen.queryByText("Step enabled")).not.toBeInTheDocument();
});

it("renders no row before the graph loads or without parked steps", () => {
  const props = { nameOf: (id: string) => id, onInspect: vi.fn() };
  const { container, rerender } = render(
    <ul>
      <SetAsideSteps graph={null} {...props} />
    </ul>,
  );
  expect(container.querySelector("ul")).toBeEmptyDOMElement();
  rerender(
    <ul>
      <SetAsideSteps
        graph={{ ...graph, nodes: graph.nodes.filter((n) => n.id !== "parked") }}
        {...props}
      />
    </ul>,
  );
  expect(container.querySelector("ul")).toBeEmptyDOMElement();
});
