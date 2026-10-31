import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { CanvasNote, NodeInstance, WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WorkflowCanvas } from "./workflow-canvas";

vi.mock("@/components/workflows/use-app-connections", () => ({
  useAppConnections: () => ({ connections: null, canConnect: false }),
  useMcpAppStep: () => null,
}));

// Adding a step reads the channel bots to start a reply wired; none are known here.
vi.mock("@/hooks/use-permissions", async (original) => ({
  ...(await original<typeof import("@/hooks/use-permissions")>()),
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("@/hooks/use-channel-bots", async (original) => ({
  ...(await original<typeof import("@/hooks/use-channel-bots")>()),
  useChannelBots: () => ({ bots: [], isLoading: false, error: null }),
}));

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
  it("keeps a single action button and groups appearance controls in its menu", async () => {
    seed([note()]);
    store.getState().setSelection({ nodeIds: ["n"], edgeIds: [] });
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    expect(container.querySelector('[data-note-id="n"]')?.querySelectorAll("button")).toHaveLength(
      1,
    );
    expect(container.querySelectorAll(".react-flow__resize-control.line")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Note actions" }));
    await userEvent.hover(screen.getByRole("menuitem", { name: "Note colour" }));
    const grey = await screen.findByRole("menuitemradio", { name: "Grey" });
    expect(grey).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Red" }));
    expect(store.getState().graph?.notes?.[0]?.color).toBe("red");
    expect(container.querySelector('[data-note-id="n"]')).toHaveClass("border-rose-500/20");
    expect(screen.queryByRole("menuitemradio")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Note actions" }));
  });

  it("opens its menu from the keyboard and closes it with Escape", async () => {
    seed([note()]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    const actions = screen.getByRole("button", { name: "Note actions" });
    actions.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("menuitem", { name: "Edit note" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(actions).toHaveFocus();
    expect(screen.queryByRole("menuitem")).toBeNull();
  });

  it("shows its markdown, and is written from its Edit button", async () => {
    seed([note()]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
    expect(await screen.findByText("Why")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Note actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit note" }));
    const field = screen.getByLabelText("Note");
    expect(field).toHaveFocus();
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

  it("writes nothing when the text is left as it was, and never opens a step's settings", async () => {
    seed([note()]);
    const { container } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);

    await userEvent.click(screen.getByRole("button", { name: "Note actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit note" }));
    fireEvent.blur(screen.getByLabelText("Note"));
    fireEvent.click(container.querySelector('[data-note-id="n"]') as HTMLElement);

    expect(stored()).toBe("**Why** this");
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("reads without editing on a read-only canvas, and stays off a loop body's", async () => {
    seed([note({ text: "" }), note({ id: "m", text: "Kept" })]);
    const { unmount } = render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} readOnly />);
    expect(screen.getByText("Kept")).toBeInTheDocument();
    expect(screen.queryByLabelText("Edit note")).toBeNull();
    await userEvent.click(
      screen.getByLabelText("Note actions", { selector: '[data-note-id="m"] button' }),
    );
    expect(screen.getByRole("menuitem", { name: "Open note" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Edit note" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Note colour" })).toBeNull();
    expect(document.querySelector(".react-flow__resize-control")).toBeNull();
    await userEvent.keyboard("{Escape}");
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
    await userEvent.click(await screen.findByRole("button", { name: "Add a note" }));

    expect(store.getState().graph?.notes).toHaveLength(1);
  });
});

it("changes note dimensions and saves expanded edits while returning focus", async () => {
  seed([note()]);
  render(<WorkflowCanvas workflow={WORKFLOW} catalog={[ACT]} />);
  await userEvent.click(screen.getByRole("button", { name: "Note actions" }));
  await userEvent.hover(screen.getByRole("menuitem", { name: "Note size" }));
  await screen.findByRole("menuitem", { name: "Wide" });
  await userEvent.click(screen.getByRole("menuitem", { name: "Wide" }));
  expect(store.getState().graph?.notes?.[0]).toMatchObject({ width: 480, height: 180 });
  await userEvent.click(screen.getByRole("button", { name: "Note actions" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Open note" }));
  const editor = screen.getByRole("dialog").querySelector("textarea");
  expect(editor).not.toBeNull();
  fireEvent.change(editor!, { target: { value: "## Updated\n\nKeep this note." } });
  await userEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(stored()).toBe("## Updated\n\nKeep this note.");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Note actions" }));
});
