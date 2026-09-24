import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { shortNodeId } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ScopeBreadcrumb } from "./scope-breadcrumb";

const store = useWorkflowEditorStore;

function def(overrides: Partial<NodeDefinition>): NodeDefinition {
  return {
    id: "control.foreach",
    version: 1,
    name: "For each",
    category: "control",
    description: "",
    kind: "control",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: [],
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
    ...overrides,
  };
}

const FOREACH = def({ id: "control.foreach", name: "For each" });
const CATALOG = [FOREACH];

function node(id: string, definitionId: string, version = 1): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: version,
    config: {},
    layout: { x: 0, y: 0 },
  };
}

/** Ids are full uuids so the short-id disambiguator is distinguishable. */
const F1 = "11111111-1111-4111-8111-111111111111";
const F2 = "22222222-2222-4222-8222-222222222222";
const GHOST = "99999999-9999-4999-8999-999999999999";

function seed(nodes: NodeInstance[]): void {
  const graph: WorkflowGraph = {
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  };
  store.getState().seedGraph(graph);
}

describe("ScopeBreadcrumb", () => {
  beforeEach(() => {
    store.getState().teardown();
  });

  it("renders nothing at the root scope", () => {
    seed([node(F1, "control.foreach")]);
    const { container } = render(<ScopeBreadcrumb catalog={CATALOG} />);
    expect(container.querySelector("nav")).toBeNull();
  });

  it("names each foreach crumb from the catalog and marks the current one", () => {
    seed([node(F1, "control.foreach"), node(F2, "control.foreach")]);
    store.getState().setScopePath([F1, F2]);
    const { getByText, getByRole } = render(<ScopeBreadcrumb catalog={CATALOG} />);

    expect(getByRole("navigation", { name: "Workflow scope" })).toBeTruthy();
    // Root crumb, then a resolved label per level (name · short id).
    expect(getByText("Workflow")).toBeTruthy();
    expect(getByText(`For each · ${shortNodeId(F1)}`)).toBeTruthy();
    const current = getByText(`For each · ${shortNodeId(F2)}`);
    expect(current.getAttribute("aria-current")).toBe("step");
  });

  it("resets to the root when the root crumb is clicked", () => {
    seed([node(F1, "control.foreach"), node(F2, "control.foreach")]);
    store.getState().setScopePath([F1, F2]);
    const { getByRole } = render(<ScopeBreadcrumb catalog={CATALOG} />);

    fireEvent.click(getByRole("button", { name: "Go to Workflow" }));
    expect(store.getState().scopePath).toEqual([]);
  });

  it("truncates to an ancestor when its crumb is clicked", () => {
    seed([node(F1, "control.foreach"), node(F2, "control.foreach")]);
    store.getState().setScopePath([F1, F2]);
    const { getByRole } = render(<ScopeBreadcrumb catalog={CATALOG} />);

    fireEvent.click(getByRole("button", { name: `Go to For each · ${shortNodeId(F1)}` }));
    expect(store.getState().scopePath).toEqual([F1]);
  });

  it("falls back to a short id when the node's definition is unknown", () => {
    seed([node(F1, "control.foreach"), node(GHOST, "gone", 9)]);
    store.getState().setScopePath([GHOST]);
    const { getByText } = render(<ScopeBreadcrumb catalog={CATALOG} />);
    expect(getByText(shortNodeId(GHOST))).toBeTruthy();
  });

  it("falls back to short ids before a graph is seeded", () => {
    store.getState().setScopePath([F1]);
    const { getByText, getByRole } = render(<ScopeBreadcrumb catalog={CATALOG} />);
    expect(getByRole("navigation", { name: "Workflow scope" })).toBeTruthy();
    expect(getByText(shortNodeId(F1))).toBeTruthy();
  });
});
