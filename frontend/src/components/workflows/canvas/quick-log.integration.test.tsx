import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance, WorkflowDetail } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WorkflowCanvas } from "./workflow-canvas";

// Adding a step reads the channel bots to start a reply wired; none are known here.
vi.mock("@/hooks/use-permissions", async (original) => ({
  ...(await original<typeof import("@/hooks/use-permissions")>()),
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("@/hooks/use-channel-bots", async (original) => ({
  ...(await original<typeof import("@/hooks/use-channel-bots")>()),
  useChannelBots: () => ({ bots: [], isLoading: false, error: null }),
}));

/** The quick log on a card: + Log, the popover, the LOG tab and its marks. */

const store = useWorkflowEditorStore;

const CATALOG = [
  makeDefinition({
    id: "logic.if",
    name: "If",
    kind: "control",
    ports: [port("in", "input", null), port("true", "output", null), port("false", "output", null)],
  }),
  makeDefinition({
    id: "http.request",
    name: "HTTP",
    ports: [port("in", "input", null), port("out", "output", null)],
  }),
  makeDefinition({
    id: "data.map",
    name: "Map",
    category: "data",
    ports: [port("in", "input", null), port("out", "output", null)],
  }),
  makeDefinition({
    id: "core.output",
    name: "Output",
    ports: [port("in", "input", null)],
  }),
  makeDefinition({
    id: "ai.classify",
    name: "Classify",
    ports: [port("in", "input", null), port("other", "output", null)],
  }),
  makeDefinition({
    id: "loop.yield",
    name: "Loop yield",
    kind: "control",
    ports: [port("in", "input", null), port("out", "output", null)],
  }),
  makeDefinition({
    id: "loop.item",
    name: "Loop item",
    kind: "control",
    ports: [port("in", "input", null), port("out", "output", null)],
  }),
];

function instance(
  id: string,
  definitionId: string,
  extra: Partial<NodeInstance> = {},
): NodeInstance {
  return {
    id,
    definition_id: definitionId,
    definition_version: 1,
    config: {},
    layout: { x: 0, y: 0 },
    ...extra,
  };
}

const WORKFLOW = {
  id: "wf",
  slug: "wf",
  name: "WF",
  description: null,
  status: "draft",
  visibility: "private",
  owner_user_id: null,
  current_version_id: null,
  live_trigger: null,
  tags: [],
  trigger_active: null,
  draft_revision: 0,
  entry_node: null,
  step_count: 0,
  last_run: null,
  created_at: null,
  updated_at: null,
  draft_graph: null,
  can_edit: true,
  settings: {
    timezone: "UTC",
    default_deadline_seconds: null,
    error_workflow_id: null,
    run_retention_days: null,
    keep_succeeded_runs: true,
    max_concurrent_runs: null,
    run_budget_usd: null,
    monthly_budget_usd: null,
    error_workflow_run_as: null,
  },
} as WorkflowDetail;

function seed(nodes: NodeInstance[]): void {
  store.getState().seedGraph({
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  });
}

const quickLogOf = (id: string) =>
  store.getState().graph?.nodes.find((n) => n.id === id)?.quick_log;

beforeEach(() => {
  store.getState().teardown();
});
afterEach(cleanup);

describe("a step's quick log", () => {
  it("adds one with the default message and every output, stored as all outputs", async () => {
    const user = userEvent.setup();
    seed([instance("i", "logic.if")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    expect(screen.getByRole("textbox")).toHaveValue("{{step}} → {{outcome}}");
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeChecked();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(quickLogOf("i")).toEqual({ message: "{{step}} → {{outcome}}", outputs: null });
    expect(screen.getByRole("button", { name: /Quick log of/ })).toBeInTheDocument();
  });

  it("stores the ticked outputs and marks each one's row", async () => {
    const user = userEvent.setup();
    seed([instance("i", "logic.if")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "went {{{{outcome}}");
    await user.click(screen.getByRole("checkbox", { name: "false" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(quickLogOf("i")).toEqual({ message: "went {{outcome}}", outputs: ["true"] });
    const rows = screen.getAllByRole("listitem");
    expect(
      within(rows[0] as HTMLElement).getByRole("img", { name: "Writes a log line" }),
    ).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).queryByRole("img")).toBeNull();
  });

  it("edits, removes, and takes each back with one undo", async () => {
    const user = userEvent.setup();
    seed([instance("i", "logic.if", { quick_log: { message: "a", outputs: null } })]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Quick log of/ }));
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "b");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(quickLogOf("i")).toEqual({ message: "b", outputs: null });
    act(() => store.getState().undo());
    expect(quickLogOf("i")).toEqual({ message: "a", outputs: null });

    await user.click(screen.getByRole("button", { name: /Quick log of/ }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(quickLogOf("i")).toBeNull();
    expect(screen.queryByRole("button", { name: /Quick log of/ })).toBeNull();
    act(() => store.getState().undo());
    expect(quickLogOf("i")).toEqual({ message: "a", outputs: null });
  });

  it("will not save with no output ticked or no message", async () => {
    const user = userEvent.setup();
    seed([instance("h", "http.request")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    await user.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("alert")).toHaveTextContent("Pick at least one output.");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.clear(screen.getByRole("textbox"));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows the tab read-only, with nothing to change, and no + Log without one", async () => {
    const user = userEvent.setup();
    seed([
      instance("i", "logic.if", { quick_log: { message: "seen", outputs: ["true"] } }),
      instance("h", "http.request"),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} readOnly />);

    expect(screen.queryByRole("button", { name: /Add a quick log to/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Quick log of/ }));
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "true" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "false" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("is not offered on a loop's own item or yield step", () => {
    seed([instance("l", "loop.item"), instance("y", "loop.yield")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    expect(screen.queryByRole("button", { name: /Add a quick log to/ })).toBeNull();
  });

  it("offers the error output of a step that routes its errors", async () => {
    const user = userEvent.setup();
    seed([instance("h", "http.request", { policy: { on_error: "route" } })]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    expect(screen.getByRole("checkbox", { name: "Error" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Error" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(quickLogOf("h")).toEqual({ message: "{{step}} → {{outcome}}", outputs: ["out"] });
  });

  it("lets a step with no outputs log, and says it logs when it fails", async () => {
    const user = userEvent.setup();
    seed([instance("o", "core.output")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText(/writes a line when it fails/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(quickLogOf("o")).toEqual({ message: "{{step}} → {{outcome}}", outputs: null });
  });

  it("drops an output the step no longer has when the quick log is saved again", async () => {
    const user = userEvent.setup();
    seed([
      instance("c", "ai.classify", {
        config: { categories: [{ name: "b" }] },
        quick_log: { message: "m", outputs: ["a", "other"] },
      }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const card = document.querySelector('[data-node-id="c"]') as HTMLElement;
    expect(within(card).getByRole("button", { name: /1 problem/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Quick log of/ }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: "b" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "other" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(quickLogOf("c")).toEqual({ message: "m", outputs: ["other"] });
    expect(within(card).queryByRole("button", { name: /problem/ })).toBeNull();
  });

  it("keeps the keyboard to the popover: Tab walks the form and shortcuts stay out", async () => {
    const user = userEvent.setup();
    seed([instance("h", "http.request")]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    act(() => store.getState().updateNodeDetails("h", { label: "Renamed" }));

    await user.click(screen.getByRole("button", { name: /Add a quick log to/ }));
    const message = screen.getByRole("textbox");
    // Enter is a line break in the message, not a save.
    await user.click(message);
    await user.keyboard("{Enter}");
    expect(quickLogOf("h")).toBeUndefined();
    // Undo is the field's own, never the canvas's.
    await user.keyboard("{Control>}z{/Control}");
    expect(store.getState().graph?.nodes[0]?.label).toBe("Renamed");

    screen.getByRole("checkbox").focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Save" })).toHaveFocus();
    // Tab did not open the step picker.
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
  });

  it("draws the log as a strip down the card, dotting the outputs it logs", () => {
    seed([
      instance("i", "logic.if", { quick_log: { message: "m", outputs: ["true"] } }),
      instance("h", "data.map", { quick_log: { message: "m", outputs: null } }),
    ]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);

    const card = (id: string) => document.querySelector(`[data-node-id="${id}"]`) as HTMLElement;
    const strip = within(card("i")).getByRole("button", { name: /Quick log of/ });
    expect(strip).toHaveTextContent("Log");
    // Docked outside the card's right side, its full height; the card's corners give way.
    expect(strip).toHaveClass("left-full", "-top-px", "-bottom-px");
    expect(card("i")).toHaveClass("rounded-r-none");
    // Only the logged output carries a mark; its row reaches across the strip.
    const marks = within(card("i")).getAllByRole("img", { name: "Writes a log line" });
    expect(marks).toHaveLength(1);
    expect(marks[0]!.closest("li")).toHaveClass("-mr-[21px]", "pr-[33px]");
    // A step with one unlabelled output gets the strip and no row to dot.
    expect(within(card("h")).getByRole("button", { name: /Quick log of/ })).toBeInTheDocument();
    expect(within(card("h")).queryByRole("img", { name: "Writes a log line" })).toBeNull();
  });

  it("flags an output the step lacks", () => {
    seed([instance("h", "http.request", { quick_log: { message: "m", outputs: ["nope"] } })]);
    render(<WorkflowCanvas workflow={WORKFLOW} catalog={CATALOG} />);
    const card = document.querySelector('[data-node-id="h"]') as HTMLElement;
    expect(within(card).getByRole("button", { name: /1 problem/ })).toBeInTheDocument();
  });
});
