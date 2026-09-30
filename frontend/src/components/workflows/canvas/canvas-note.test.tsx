import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { CanvasNote, NodeInstance, WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WorkflowCanvas } from "./workflow-canvas";

const store = useWorkflowEditorStore;
const ACT = makeDefinition({
  id: "act.one",
  name: "Act",
  category: "data",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const WORKFLOW = { id: "wf", draft_graph: null } as unknown as WorkflowDetail;
const STEP: NodeInstance = {
  id: "a",
  definition_id: "act.one",
  definition_version: 1,
  config: {},
  layout: { x: 0, y: 0 },
};

function seed(notes: CanvasNote[]) {
  store.getState().seedGraph({
    entry_node_id: "a",
    nodes: [STEP],
    edges: [],
    bindings: [],
    scopes: [],
    notes,
  });
}

const note = (overrides: Partial<CanvasNote> = {}): CanvasNote => ({
  id: "n",
  text: "**Why** this",
  layout: { x: 0, y: 200 },
  ...overrides,
});
const stored = () => store.getState().graph?.notes?.[0]?.text;

afterEach(() => store.getState().teardown());

describe("a note on the canvas", () => {
  it("shows its markdown, and is written from its Edit button", async () => {
    seed([note()]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    expect(await screen.findByText("Why")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Edit note"));
    const field = screen.getByLabelText("Note");
    fireEvent.change(field, { target: { value: "Changed" } });
    fireEvent.blur(field);

    expect(stored()).toBe("Changed");
  });

  it("opens on a double-click, and Escape keeps the text as it was", () => {
    seed([note({ text: "" })]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    expect(screen.getByText("Double-click to write a note")).toBeInTheDocument();

    fireEvent.dblClick(screen.getByText("Double-click to write a note"));
    const field = screen.getByLabelText("Note");
    fireEvent.change(field, { target: { value: "Dropped" } });
    fireEvent.keyDown(field, { key: "Escape" });

    expect(screen.queryByLabelText("Note")).toBeNull();
    expect(stored()).toBe("");
  });

  it("writes nothing when the text is left as it was, and never opens a step's settings", () => {
    seed([note()]);
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);

    fireEvent.click(screen.getByLabelText("Edit note"));
    fireEvent.blur(screen.getByLabelText("Note"));
    fireEvent.click(container.querySelector('[data-note-id="n"]') as HTMLElement);

    expect(stored()).toBe("**Why** this");
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("reads without editing on a read-only canvas, and stays off a loop body's", () => {
    seed([note({ text: "" }), note({ id: "m", text: "Kept" })]);
    const { unmount } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} readOnly />);
    expect(screen.getByText("Kept")).toBeInTheDocument();
    expect(screen.queryByLabelText("Edit note")).toBeNull();
    fireEvent.dblClick(screen.getByText("Kept"));
    expect(screen.queryByLabelText("Note")).toBeNull();
    unmount();

    store.getState().setScopePath(["a"]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    expect(screen.queryByText("Kept")).toBeNull();
  });

  it("is added where the canvas was right-clicked", async () => {
    seed([]);
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);

    fireEvent.contextMenu(
      container.querySelector('[data-workflow-region="canvas"]') as HTMLElement,
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Add a note here" }));

    expect(store.getState().graph?.notes).toHaveLength(1);
  });
});
