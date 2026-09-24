import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { NodeDefinition, WorkflowDetail, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WorkflowCanvas } from "./workflow-canvas";

const store = useWorkflowEditorStore;

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
const FOREACH = def({
  id: "control.foreach",
  name: "For each",
  kind: "control",
  ports: [
    { id: "in", label: "In", kind: "input", schema: null },
    { id: "body", label: "Body", kind: "output", schema: null },
    { id: "out", label: "Out", kind: "output", schema: null },
  ],
});
const CATALOG = [ACTION, FOREACH];

const FID = "ffffffff-ffff-4fff-8fff-ffffffffffff";

function node(id: string, definitionId: string) {
  return {
    id,
    definition_id: definitionId,
    definition_version: 1,
    config: {},
    layout: { x: 0, y: 0 },
  };
}

/** A foreach `F` at the root owning a one-node body `b1`. */
function seedForeach(): void {
  const graph: WorkflowGraph = {
    entry_node_id: FID,
    nodes: [node(FID, "control.foreach"), node("b1", "act")],
    edges: [],
    bindings: [],
    scopes: [
      {
        scope_node_id: FID,
        body_node_ids: ["b1"],
        entry_port: "body",
        exit_node_id: FID,
        exit_port: "out",
      },
    ],
  };
  store.getState().seedGraph(graph);
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

describe("WorkflowCanvas scope view", () => {
  beforeEach(() => {
    store.getState().teardown();
  });

  it("draws only the root scope's nodes and offers a way into the foreach", () => {
    seedForeach();
    const { getByText, queryByText, container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} />,
    );
    // The foreach node shows at the root; its body node does not.
    expect(getByText("For each")).toBeTruthy();
    expect(queryByText("Act")).toBeNull();
    // No breadcrumb at the root.
    expect(container.querySelector("nav")).toBeNull();
    // The card carries a keyboard-reachable enter control.
    expect(container.querySelector('button[aria-label="Open the body of For each"]')).toBeTruthy();
  });

  it("enters the foreach body, then walks back out through the breadcrumb", async () => {
    seedForeach();
    const { getByText, queryByText, getByRole, container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} />,
    );

    fireEvent.click(container.querySelector('button[aria-label="Open the body of For each"]')!);
    expect(store.getState().scopePath).toEqual([FID]);

    // The body node is now shown, the foreach node is not, and the breadcrumb appears.
    await waitFor(() => expect(getByText("Act")).toBeTruthy());
    expect(queryByText("For each")).toBeNull();
    expect(getByRole("navigation", { name: "Workflow scope" })).toBeTruthy();

    fireEvent.click(getByRole("button", { name: "Go to Workflow" }));
    expect(store.getState().scopePath).toEqual([]);
    await waitFor(() => expect(getByText("For each")).toBeTruthy());
    expect(queryByText("Act")).toBeNull();
  });

  it("offers no enter control when read-only", () => {
    seedForeach();
    const { container } = render(
      <WorkflowCanvas workflow={workflow()} catalog={CATALOG} readOnly />,
    );
    expect(container.querySelector('button[aria-label="Open the body of For each"]')).toBeNull();
  });
});
