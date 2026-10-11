import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";

import { WorkflowStatus } from "./workflow-status";

const live = vi.hoisted(() => ({ version: undefined as unknown }));
vi.mock("@/hooks", () => ({ useWorkflowVersion: () => ({ version: live.version }) }));

const graph: WorkflowGraph = {
  entry_node_id: "a",
  nodes: [
    {
      id: "a",
      definition_id: "trigger.manual",
      definition_version: 1,
      config: {},
      layout: { x: 0, y: 0 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

function workflow(overrides: Partial<WorkflowDetail> = {}): WorkflowDetail {
  return {
    id: "w1",
    status: "published",
    current_version_id: "v1",
    ...overrides,
  } as WorkflowDetail;
}

beforeEach(() => {
  live.version = undefined;
});

describe("WorkflowStatus", () => {
  it("says a workflow never published is a draft, and an archived one is archived", () => {
    const { unmount } = render(
      <WorkflowStatus
        workflow={workflow({ status: "draft", current_version_id: null })}
        draft={graph}
      />,
    );
    expect(screen.getByText("Draft, not published")).toBeInTheDocument();
    unmount();
    render(<WorkflowStatus workflow={workflow({ status: "archived" })} draft={graph} />);
    expect(screen.getByText("Archived")).toBeInTheDocument();
  });

  it("names the live version, and says when the draft has changes it does not", () => {
    const { unmount, rerender } = render(<WorkflowStatus workflow={workflow()} draft={graph} />);
    // Until the live version is read, only that it is live.
    expect(screen.getByText("Live")).toBeInTheDocument();

    live.version = { version: 3, graph };
    rerender(<WorkflowStatus workflow={workflow()} draft={graph} />);
    expect(screen.getByText("Live · version 3")).toBeInTheDocument();
    expect(screen.queryByText("Unpublished changes")).toBeNull();
    // Moved on the canvas only: nothing a publish would carry.
    const moved = { ...graph, nodes: [{ ...graph.nodes[0]!, layout: { x: 90, y: 0 } }] };
    rerender(<WorkflowStatus workflow={workflow()} draft={moved} />);
    expect(screen.queryByText("Unpublished changes")).toBeNull();

    const edited = { ...graph, nodes: [{ ...graph.nodes[0]!, label: "Start" }] };
    rerender(<WorkflowStatus workflow={workflow()} draft={edited} />);
    expect(screen.getByText("Unpublished changes")).toBeInTheDocument();
    unmount();

    render(<WorkflowStatus workflow={workflow()} draft={null} />);
    expect(screen.queryByText("Unpublished changes")).toBeNull();
  });

  it("counts a connection added or taken away as a change", () => {
    const wired = {
      ...graph,
      edges: [
        {
          id: "e",
          source_node_id: "a",
          source_port: "out",
          target_node_id: "a",
          target_port: "in",
        },
      ],
    };
    live.version = { version: 1, graph };
    const { rerender } = render(<WorkflowStatus workflow={workflow()} draft={wired} />);
    expect(screen.getByText("Unpublished changes")).toBeInTheDocument();

    live.version = { version: 1, graph: wired };
    rerender(<WorkflowStatus workflow={workflow()} draft={graph} />);
    expect(screen.getByText("Unpublished changes")).toBeInTheDocument();
  });
});
