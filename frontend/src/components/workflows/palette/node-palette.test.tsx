import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NODE_DRAG_MIME } from "./drag";
import { NodePalette } from "./node-palette";

function def(overrides: Partial<NodeDefinition> & Pick<NodeDefinition, "id">): NodeDefinition {
  return {
    version: 1,
    name: overrides.id,
    category: "General",
    description: "",
    kind: "action",
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

const FETCH = def({
  id: "http.fetch",
  name: "Fetch",
  category: "Network",
  description: "Call an HTTP endpoint",
  kind: "action",
});
const BRANCH = def({
  id: "logic.branch",
  name: "Branch",
  category: "Logic",
  description: "Choose a path",
  kind: "control",
});
const FOREACH = def({
  id: "control.foreach",
  name: "For each",
  category: "Logic",
  description: "Repeat over a list",
  kind: "control",
});
const WAIT = def({
  id: "time.wait",
  name: "Wait",
  category: "Timing",
  description: "",
  kind: "waiting",
});

const CATALOG = [FETCH, BRANCH, FOREACH, WAIT];

const insertNode = vi.fn();

/** Seed the store with a scope path, an empty working graph and a recorded `insertNode`. */
function seedStore(scopePath: string[] = []) {
  useWorkflowEditorStore.setState({
    scopePath,
    graph: { entry_node_id: "", nodes: [], edges: [], bindings: [], scopes: [] },
    selection: { nodeIds: [], edgeIds: [] },
    insertNode,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  seedStore();
});

function addButton(name: string): HTMLElement {
  return screen.getByRole("button", { name: `Add ${name}` });
}

describe("NodePalette", () => {
  it("groups the catalog by category with a node under each", () => {
    render(<NodePalette nodes={CATALOG} />);

    expect(screen.getByRole("button", { name: "Network" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Timing" })).toBeVisible();
    // Two nodes share the Logic category — one group header, both rows under it.
    const logic = screen.getByRole("button", { name: "Logic" }).parentElement as HTMLElement;
    expect(within(logic).getByRole("button", { name: "Add Branch" })).toBeVisible();
    expect(within(logic).getByRole("button", { name: "Add For each" })).toBeVisible();
  });

  it("folds a group away and back", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.click(screen.getByRole("button", { name: "Logic" }));
    expect(screen.queryByRole("button", { name: "Add Branch" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Logic" }));
    expect(addButton("Branch")).toBeVisible();
  });

  it("shows an empty message when the catalog holds no node types", () => {
    render(<NodePalette nodes={[]} />);

    expect(screen.getByText("No node types are available.")).toBeVisible();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("filters by name", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.type(screen.getByLabelText("Search nodes"), "fetch");

    expect(addButton("Fetch")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add Wait" })).toBeNull();
  });

  it("filters by description", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.type(screen.getByLabelText("Search nodes"), "endpoint");

    expect(addButton("Fetch")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add Branch" })).toBeNull();
  });

  it("filters by category", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.type(screen.getByLabelText("Search nodes"), "timing");

    expect(addButton("Wait")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add Fetch" })).toBeNull();
  });

  it("says so when the search matches nothing", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.type(screen.getByLabelText("Search nodes"), "zzz");

    expect(screen.getByText("No nodes match your search.")).toBeVisible();
  });

  it("adds a node on click, planned by the canvas's insertion rules", async () => {
    render(<NodePalette nodes={CATALOG} />);

    await userEvent.click(addButton("Fetch"));

    // The first step of an empty graph: at the origin, the entry, wired to nothing.
    expect(insertNode).toHaveBeenCalledWith(
      expect.objectContaining({
        node: expect.objectContaining({ definition_id: FETCH.id, layout: { x: 0, y: 0 } }),
        edge: null,
        becomesEntry: true,
      }),
    );
  });

  it("writes the definition onto a drag for the canvas to drop", () => {
    render(<NodePalette nodes={CATALOG} />);
    const setData = vi.fn();

    fireEvent.dragStart(addButton("Fetch"), {
      dataTransfer: { setData, effectAllowed: "none" },
    });

    expect(setData).toHaveBeenCalledWith(NODE_DRAG_MIME, JSON.stringify(FETCH));
  });

  it("hides a loop once loops are nested as deep as publishing allows", () => {
    seedStore(["fe-1", "fe-2", "fe-3"]);
    render(<NodePalette nodes={CATALOG} />);

    expect(screen.queryByRole("button", { name: "Add For each" })).toBeNull();
    expect(addButton("Branch")).toBeVisible();
    expect(addButton("Fetch")).toBeVisible();
  });

  it("offers foreach at the root scope", () => {
    render(<NodePalette nodes={CATALOG} />);

    expect(addButton("For each")).toBeVisible();
  });
});
