import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { DEBUG_ECHO, echo, graph, node } from "@/components/workflows/validation/fixtures";

import { PropertyPanel } from "./property-panel";

interface StoreState {
  selection: { nodeIds: string[]; edgeIds: string[] };
  getGraph: () => WorkflowGraph | null;
  getSelectedNode: () => NodeInstance | null;
  setSelection: (selection: unknown) => void;
  updateNodeConfig: () => void;
  upsertBinding: () => void;
  removeBinding: () => void;
}

const store: { current: StoreState } = { current: null as unknown as StoreState };
const catalog: { current: { nodes: unknown[]; isLoading: boolean } } = {
  current: { nodes: [], isLoading: false },
};

vi.mock("@/stores/workflow-editor-store", () => ({
  useWorkflowEditorStore: () => store.current,
}));
vi.mock("@/hooks", () => ({
  useNodeCatalog: () => catalog.current,
}));

function baseStore(over: Partial<StoreState> = {}): StoreState {
  return {
    selection: { nodeIds: [], edgeIds: [] },
    getGraph: () => null,
    getSelectedNode: () => null,
    setSelection: vi.fn(),
    updateNodeConfig: vi.fn(),
    upsertBinding: vi.fn(),
    removeBinding: vi.fn(),
    ...over,
  };
}

beforeEach(() => {
  catalog.current = { nodes: [DEBUG_ECHO], isLoading: false };
  store.current = baseStore();
});

describe("PropertyPanel", () => {
  it("shows the empty state when no graph is loaded", () => {
    render(<PropertyPanel />);
    expect(screen.getByText("Select a node to edit it.")).toBeVisible();
  });

  it("runs no validation while the catalog is still loading", () => {
    catalog.current = { nodes: [], isLoading: true };
    store.current = baseStore({
      getGraph: () => graph({ entry: "A", nodes: [node("A", "missing")] }),
    });
    render(<PropertyPanel />);
    // A loading catalog produces no problems, so no footer.
    expect(screen.queryByRole("button", { name: /problem/ })).toBeNull();
  });

  it("builds the form for the store's selected node", () => {
    const selected = echo("A");
    store.current = baseStore({
      selection: { nodeIds: ["A"], edgeIds: [] },
      getGraph: () => graph({ entry: "A", nodes: [selected] }),
      getSelectedNode: () => selected,
    });
    render(<PropertyPanel />);
    expect(screen.getByRole("heading", { name: "Echo · A" })).toBeVisible();
    expect(screen.getByText("Configuration")).toBeVisible();
  });

  it("selects a node's node when its problem is clicked", async () => {
    const setSelection = vi.fn();
    store.current = baseStore({
      setSelection,
      getGraph: () => graph({ entry: "A", nodes: [node("A", "missing")] }),
    });
    render(<PropertyPanel />);
    await userEvent.click(screen.getByRole("button", { name: "1 problem" }));
    await userEvent.click(screen.getByRole("button", { name: /unknown node/ }));
    expect(setSelection).toHaveBeenCalledWith({ nodeIds: ["A"], edgeIds: [] });
  });
});
