import { act, createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEBUG_ECHO,
  REQUIRED_INPUT,
  makeDefinition,
} from "@/components/workflows/validation/fixtures";
import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { WORKFLOW_APPS } from "@/components/workflows/apps";
import type { McpAppStep } from "@/components/workflows/use-app-connections";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

import { NodeEditorDialog } from "./node-editor-dialog";

vi.mock("@/hooks", () => ({
  useWorkflowRuns: () => ({ start: { mutate: vi.fn() } }),
  useWorkflowTable: () => ({ table: null }),
}));
vi.mock("./step-evals", async (original) => ({
  ...(await original<typeof import("./step-evals")>()),
  StepEvals: () => <p>the step&apos;s evals</p>,
}));

vi.mock("@/components/workflows/canvas/node-resource", async (original) => ({
  ...(await original<typeof import("@/components/workflows/canvas/node-resource")>()),
  AgentTile: ({ agentId }: { agentId: string }) => <span>face of {agentId}</span>,
  InlineAgentTile: ({ name }: { name: string }) => <span>own face of {name}</span>,
}));

vi.mock("@/components/workflows/pickers/mcp-tool-picker", async (original) => ({
  ...(await original<typeof import("@/components/workflows/pickers/mcp-tool-picker")>()),
  useMcpToolSchema: () => null,
}));
const mcpApp = vi.hoisted(() => ({ step: null as McpAppStep | null }));
vi.mock("@/components/workflows/use-app-connections", () => ({
  useMcpAppStep: () => mcpApp.step,
}));

const store = useWorkflowEditorStore;

function node(id: string, definitionId = "debug.echo", config = {}): NodeInstance {
  return { id, definition_id: definitionId, definition_version: 1, config, layout: { x: 0, y: 0 } };
}

function seed(...nodes: NodeInstance[]) {
  const graph: WorkflowGraph = {
    entry_node_id: nodes[0]?.id ?? "",
    nodes,
    edges: [],
    bindings: [],
    scopes: [],
  };
  store.getState().seedGraph(graph);
}

afterEach(() => {
  mcpApp.step = null;
  store.getState().teardown();
});

describe("NodeEditorDialog", () => {
  it("offers a model step's evals to an editor, and no other step's", async () => {
    const classify = { ...DEBUG_ECHO, id: "ai.classify", name: "Classify" };
    seed(node("a", "ai.classify"), node("b"));
    store.getState().editNode("a");
    const { unmount } = render(
      <NodeEditorDialog workflowId="wf" catalog={[classify, DEBUG_ECHO]} />,
    );
    await userEvent.click(screen.getByRole("tab", { name: "Evals" }));
    expect(screen.getByText("the step's evals")).toBeTruthy();
    unmount();

    store.getState().editNode("b");
    render(<NodeEditorDialog workflowId="wf" catalog={[classify, DEBUG_ECHO]} />);
    expect(screen.queryByRole("tab", { name: "Evals" })).toBeNull();
  });

  it("says an MCP call on an app's connection is one, on which connection and tool, with a link to it", () => {
    const call = { ...DEBUG_ECHO, id: "mcp.call", name: "Call an MCP tool", category: "mcp" };
    seed(node("a", "mcp.call", { connection_id: "c1", tool: "draft_gmail_message" }));
    store.getState().editNode("a");
    mcpApp.step = {
      app: WORKFLOW_APPS[0] as McpAppStep["app"],
      connection: {
        id: "c1",
        name: "gmail-dev",
        label: null,
        catalog_key: "google-workspace",
      } as OrgMcpConnectionRecord,
      tool: "draft_gmail_message",
    };
    const { unmount } = render(<NodeEditorDialog catalog={[call]} />);

    expect(
      screen.getByText(
        "MCP tool call: Create draft (draft_gmail_message) on the connection gmail-dev.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the connection" })).toHaveAttribute(
      "href",
      "/mcp-servers?server=google-workspace",
    );
    unmount();

    // Another connection's call, or one with no tool yet, says nothing extra.
    mcpApp.step = null;
    render(<NodeEditorDialog catalog={[call]} />);
    expect(screen.queryByText(/MCP tool call:/)).toBeNull();
  });

  it("opens nothing until a step is being edited", () => {
    seed(node("a"));
    const { container } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the step's name, what it does and its settings, and closes on Done", async () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    expect(screen.getByRole("heading", { name: "Echo" })).toBeTruthy();
    expect(screen.getByText(DEBUG_ECHO.description)).toBeTruthy();
    expect(screen.getByDisplayValue("hi")).toBeTruthy();
    expect(store.getState().selection.nodeIds).toEqual(["a"]);

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("heads a step that runs an agent with the agent's face", () => {
    seed(node("a", "debug.echo", { agent: { agent_id: "a1", version_id: null } }));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    expect(screen.getByText("face of a1")).toBeInTheDocument();
  });

  it("heads a step that configures its own agent with that agent's face", () => {
    seed(node("a", "debug.echo", { inline: { name: "Lead scorer" } }));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    expect(screen.getByText("own face of Lead scorer")).toBeInTheDocument();
  });

  it("scrolls a long form between its header and footer when it has no data panes", () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly />);
    // Only capped in height, so the body - a child of the dialog itself - has to be
    // what scrolls; a scroller nested deeper never gets a height to scroll in.
    const scroller = screen.getByDisplayValue("hi").closest(".overflow-y-auto");
    expect(scroller?.parentElement).toBe(screen.getByRole("dialog"));
  });

  it("scrolls its form at the edge while a field from the Input pane is dragged", () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly />);
    const body = screen.getByDisplayValue("hi").closest(".overflow-y-auto") as HTMLElement;
    // jsdom loads no stylesheet: the class's overflow is given as a style.
    body.style.overflowY = "auto";
    Object.defineProperty(body, "scrollHeight", { value: 2000 });
    Object.defineProperty(body, "clientHeight", { value: 400 });
    body.getBoundingClientRect = () => ({ top: 0, bottom: 400 }) as DOMRect;
    // jsdom builds a drag event without a pointer position: it is set on the event.
    const dragAt = (types: string[]) => {
      const target = screen.getByDisplayValue("hi");
      const event = createEvent.dragOver(target, { dataTransfer: { types } });
      Object.defineProperty(event, "clientY", { value: 399 });
      fireEvent(target, event);
    };

    dragAt(["application/x-agenticos-step-field"]);
    expect(body.scrollTop).toBeGreaterThan(0);
    // Any other drag - a file, a step from the picker - scrolls nothing.
    const before = body.scrollTop;
    dragAt(["Files"]);
    expect(body.scrollTop).toBe(before);
  });

  it("deletes the step it shows", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete step" }));
    expect(store.getState().graph?.nodes.map((item) => item.id)).toEqual(["a"]);
    expect(store.getState().editingNodeId).toBeNull();
  });

  it("reads without writing on a read-only editor, and says when a step's type is unknown", () => {
    seed(node("u", "gone.step"));
    store.getState().editNode("u");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} readOnly />);
    expect(screen.queryByRole("button", { name: "Delete step" })).toBeNull();
    expect(screen.getByText("This node's type is not in the catalog.")).toBeTruthy();
    // Its problem - a type nobody can publish - is said under its name.
    expect(screen.getByText(/uses an unknown node: gone\.step/)).toBeTruthy();
  });
});

describe("a step's own name and whether it runs", () => {
  it("renames the step in the header, and says what kind of step a renamed one is", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);

    // Two Echo steps: the header tells this one apart the way the canvas does.
    await userEvent.click(screen.getByRole("button", { name: /^Echo/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Step name" }), "Say hi{Enter}");

    expect(store.getState().graph?.nodes[1]?.label).toBe("Say hi");
    expect(screen.getByRole("heading", { name: "Say hi" })).toBeTruthy();
    expect(screen.getByText(`Echo · ${DEBUG_ECHO.description}`)).toBeTruthy();
  });

  it("switches a step off in its Settings, but not the step the workflow starts from", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    const { unmount } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByRole("switch", { name: "Run this step" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    await userEvent.click(screen.getByRole("switch", { name: "Run this step" }));
    expect(store.getState().graph?.nodes[1]?.disabled).toBe(true);
    // The tab says a setting is not at its default.
    expect(screen.getByLabelText("Some settings are changed")).toBeTruthy();
    unmount();

    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.queryByRole("switch", { name: "Run this step" })).toBeNull();
    expect(screen.getByLabelText("Note")).toBeTruthy();
  });
});

describe("a read-only step's Settings", () => {
  it("shows every setting disabled at its default, rather than nothing", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} readOnly />);
    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));

    const runs = screen.getByRole("switch", { name: "Run this step" });
    expect(runs).toBeDisabled();
    expect(runs).toBeChecked();
    expect(screen.getByRole("heading", { name: "When it is slow or fails" })).toBeTruthy();
    expect(screen.getByLabelText("Note")).toBeDisabled();
  });
});

describe("a step looked at in a run", () => {
  it("folds its settings away and offers nothing about slowness or failure it did not have", async () => {
    seed(node("a", "debug.echo", { message: "hi" }), node("b", "debug.echo", { message: "yo" }));
    store.getState().editNode("b");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly runData />);

    const fold = screen.getByText("Settings this step ran with");
    expect(fold.closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: /When it is slow or fails/ })).toBeNull();
    await userEvent.click(fold);
    expect(fold.closest("details")).toHaveAttribute("open");
    expect(screen.getByDisplayValue("yo")).toBeDisabled();
  });

  it("shows only what the run's first step handed on, its settings folded under it", () => {
    seed(node("a", "debug.echo", { message: "hi" }), node("b"));
    store.getState().editNode("a");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly runData />);

    expect(screen.queryByRole("region", { name: "Input" })).toBeNull();
    const output = screen.getByRole("region", { name: "Output" });
    // One column of data, with the settings below it rather than beside it.
    expect(output.closest(".grid")).toHaveClass("lg:grid-rows-[minmax(0,1fr)_auto]");
    expect(output.closest(".grid")).not.toHaveClass("lg:grid-cols-2");
  });
});

describe("a step's data", () => {
  it("sits between what the step reads and what it hands on, while editing a workflow", () => {
    seed(node("a", "debug.echo", { message: "hi" }), node("b", "debug.echo", { message: "yo" }));
    store.getState().editNode("b");
    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} />);

    expect(screen.getByRole("region", { name: "Input" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Output" })).toBeTruthy();
  });

  it("has no Input for the step a workflow starts from, and no data on a read-only editor", () => {
    seed(node("a", "debug.echo", { message: "hi" }));
    store.getState().editNode("a");
    const { unmount } = render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByRole("region", { name: "Input" })).toBeNull();
    expect(screen.getByRole("region", { name: "Output" })).toBeTruthy();
    unmount();

    render(<NodeEditorDialog workflowId="wf" catalog={[DEBUG_ECHO]} readOnly />);
    expect(screen.queryByRole("region", { name: "Output" })).toBeNull();
  });
});

describe("a step's missing values", () => {
  const NEEDS = makeDefinition({ id: "test.needs", name: "Needs", input_schema: REQUIRED_INPUT });
  // What a field itself says, apart from the header line that names it.
  const NOT_TYPED = "Required: type a value, or take one from an earlier step.";
  const NOT_SET = "Required: the step cannot run without it.";

  it("names a missing value in its header at once, and under its field once a run is tried", () => {
    seed(node("a", "test.needs"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NEEDS]} />);
    // The header agrees with the card's count from the start.
    expect(screen.getByRole("button", { name: `Value: ${NOT_TYPED}` })).toBeInTheDocument();
    expect(screen.queryByText(NOT_TYPED)).toBeNull();

    act(() => store.getState().revealProblems());

    expect(screen.getByText(NOT_TYPED)).toBeInTheDocument();
  });

  const NOTED = makeDefinition({
    id: "test.noted",
    name: "Noted",
    input_schema: REQUIRED_INPUT,
    config_schema: {
      type: "object",
      properties: { subject: { type: "string", title: "Subject" } },
      required: ["subject"],
    },
  });

  it("says it under a field once the field was left, and forgets that when the dialog closes", () => {
    seed(node("a", "test.noted"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NOTED]} />);

    // Each field says it is missing once it was left, and not before.
    expect(screen.queryByText(NOT_SET)).toBeNull();
    fireEvent.focusOut(screen.getByLabelText(/^Subject/));
    expect(screen.getByText(NOT_SET)).toBeInTheDocument();
    expect(screen.queryByText(NOT_TYPED)).toBeNull();

    const input = document.querySelector("[data-field='value'] input") as HTMLElement;
    fireEvent.focusOut(input);
    fireEvent.focusOut(input);
    expect(screen.getByText(NOT_TYPED)).toBeInTheDocument();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    act(() => store.getState().editNode("a"));
    expect(screen.queryByText(NOT_TYPED)).toBeNull();
  });

  it("takes a header problem to its field, which then says it", async () => {
    seed(node("a", "test.noted"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NOTED]} />);
    expect(screen.queryByText(NOT_SET)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: `Subject: ${NOT_SET}` }));

    expect(screen.getByText(NOT_SET)).toBeInTheDocument();
    expect(screen.queryByText(NOT_TYPED)).toBeNull();
  });

  it("goes back to Parameters for a header problem, scrolls to its field and types into it", async () => {
    const scrolled = vi.fn();
    const scrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrolled;
    try {
      seed(node("a"), node("b", "test.noted"));
      store.getState().editNode("b");
      render(<NodeEditorDialog catalog={[NOTED]} />);
      await userEvent.click(screen.getByRole("tab", { name: "Settings" }));

      await userEvent.click(screen.getByRole("button", { name: `Value: ${NOT_TYPED}` }));

      expect(screen.getByRole("tab", { name: "Parameters" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      const field = document.querySelector("[data-field='value']") as HTMLElement;
      // The field's own box, not the Data menu in the label row above it.
      await waitFor(() => expect(document.activeElement).toBe(field.querySelector("input")));
      expect(scrolled.mock.contexts).toContain(field);
    } finally {
      Element.prototype.scrollIntoView = scrollIntoView;
    }
  });

  it("takes a header problem to a field with no box to its first control", async () => {
    const CHOSEN = makeDefinition({
      id: "test.chosen",
      name: "Chosen",
      config_schema: {
        type: "object",
        properties: { mode: { type: "string", title: "Mode", enum: ["fast", "slow"] } },
        required: ["mode"],
      },
    });
    seed(node("a", "test.chosen"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[CHOSEN]} />);

    await userEvent.click(screen.getByRole("button", { name: `Mode: ${NOT_SET}` }));

    const field = document.querySelector("[data-field='mode']") as HTMLElement;
    await waitFor(() => expect(document.activeElement).toBe(field.querySelector("button")));
  });

  it("has not left a field while focus moves into its own list", () => {
    seed(node("a", "test.noted"));
    store.getState().editNode("a");
    render(<NodeEditorDialog catalog={[NOTED]} />);
    const popup = document.createElement("div");
    popup.setAttribute("data-radix-popper-content-wrapper", "");
    const option = popup.appendChild(document.createElement("button"));
    document.body.appendChild(popup);

    fireEvent.focusOut(screen.getByLabelText(/^Subject/), { relatedTarget: option });

    expect(screen.queryByText(NOT_SET)).toBeNull();
    popup.remove();
  });
});

describe("a step's run policy", () => {
  it("sits in the step's Settings, apart from what the step does", async () => {
    seed(node("a"), node("b"));
    store.getState().editNode("b");
    const { unmount } = render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.queryByText("Handle errors")).toBeNull();
    expect(screen.queryByLabelText("Some settings are changed")).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByText("Handle errors")).toBeInTheDocument();
    unmount();

    // A step with a policy says so on the tab, before it is opened.
    seed(node("a"), { ...node("b"), policy: { timeout_seconds: 5 } });
    store.getState().editNode("b");
    render(<NodeEditorDialog catalog={[DEBUG_ECHO]} />);
    expect(screen.getByLabelText("Some settings are changed")).toBeTruthy();
  });
});
