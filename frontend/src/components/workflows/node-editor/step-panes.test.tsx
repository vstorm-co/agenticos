import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { edge, makeDefinition, node, port } from "@/components/workflows/validation/fixtures";
import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { InputPane, OutputPane } from "./step-panes";

const mutate = vi.fn();
const start = { mutate, isPending: false };
vi.mock("@/hooks", () => ({ useWorkflowRuns: () => ({ start }) }));

const store = useWorkflowEditorStore;
const STEP = makeDefinition({
  id: "test.step",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const WRITER = { ...STEP, effect_kind: "write" as const };
const DECIDE = makeDefinition({
  id: "logic.if",
  kind: "control",
  ports: [port("in", "input", null), port("true", "output", null)],
});
const MANUAL = makeDefinition({
  id: "trigger.manual",
  category: "triggers",
  ports: [port("out", "output", null)],
});

function line(
  second: Partial<NodeInstance> = {},
  first: NodeInstance = node("a", "test.step"),
): WorkflowGraph {
  return {
    entry_node_id: first.id,
    nodes: [first, { ...node("b", "test.step"), ...second }],
    edges: [edge("e", first.id, "out", "b", "in")],
    bindings: [],
    scopes: [],
  };
}

function seed(graph: WorkflowGraph) {
  store.getState().seedGraph(graph);
}

function renderOutput(definition: NodeDefinition = STEP, catalog = [STEP]) {
  const graph = store.getState().graph as WorkflowGraph;
  const shown = graph.nodes.find((candidate) => candidate.id === "b") as NodeInstance;
  return render(
    <OutputPane
      workflowId="wf"
      catalog={catalog}
      graph={graph}
      node={shown}
      definition={definition}
    />,
  );
}

const KNOWN = { output: { echoed: "hi" }, error: null, runId: "r" };

beforeEach(() => {
  mutate.mockReset();
  mutate.mockImplementation((_body, options) => options?.onSuccess?.({ id: "run-2" }));
});
afterEach(() => store.getState().teardown());

describe("InputPane", () => {
  it("says a step with nothing before it reads nothing", () => {
    const graph = line();
    render(<InputPane graph={graph} node={graph.nodes[0] as NodeInstance} names={new Map()} />);
    expect(screen.getByText(/Nothing comes into this step/)).toBeTruthy();
  });

  it("shows each step it reads from: pinned, from the last run, or not yet run", () => {
    const graph: WorkflowGraph = {
      ...line(),
      nodes: [
        { ...node("a", "test.step"), pinned_output: { echoed: "pinned" } },
        node("x", "test.step"),
        node("b", "test.step"),
      ],
      edges: [edge("e", "a", "out", "b", "in"), edge("f", "x", "out", "b", "in")],
    };
    seed(graph);
    render(
      <InputPane
        graph={graph}
        node={graph.nodes[2] as NodeInstance}
        names={new Map([["a", "First"]])}
      />,
    );

    expect(screen.getByText("First")).toBeTruthy();
    expect(screen.getByText("Pinned")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "pinned" })).toBeTruthy();
    expect(screen.getByText("x")).toBeTruthy();
    expect(screen.getByText(/No data yet/)).toBeTruthy();
  });
});

describe("OutputPane", () => {
  it("says there is no output yet, and writes data to pin", async () => {
    seed(line());
    renderOutput();
    expect(screen.getByText(/No output yet/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Write data to pin" }));
    const editor = screen.getByLabelText("Pinned data as JSON");
    expect(editor).toHaveValue("{}");
    fireEvent.change(editor, { target: { value: '{"echoed": "typed"}' } });
    await userEvent.click(screen.getByRole("button", { name: "Pin" }));

    expect(store.getState().graph?.nodes[1]?.pinned_output).toEqual({ echoed: "typed" });
  });

  it("refuses pinned data that is not a JSON object, or too large, and cancels", async () => {
    seed(line());
    renderOutput();
    await userEvent.click(screen.getByRole("button", { name: "Write data to pin" }));
    const editor = screen.getByLabelText("Pinned data as JSON");
    const save = screen.getByRole("button", { name: "Pin" });

    fireEvent.change(editor, { target: { value: "{" } });
    await userEvent.click(save);
    expect(screen.getByText("This is not valid JSON.")).toBeTruthy();
    fireEvent.change(editor, { target: { value: "[1]" } });
    await userEvent.click(save);
    expect(screen.getByText(/Pinned data is a JSON object/)).toBeTruthy();
    fireEvent.change(editor, { target: { value: JSON.stringify({ x: "y".repeat(64_000) }) } });
    await userEvent.click(save);
    expect(screen.getByText("Pinned data may take at most 64000 bytes.")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Pinned data as JSON")).toBeNull();
    expect(store.getState().graph?.nodes[1]?.pinned_output).toBeUndefined();
  });

  it("pins what the step handed on last time, edits it and unpins it", async () => {
    seed(line());
    store.getState().mergeStepData({ b: KNOWN });
    const { rerender } = renderOutput();
    expect(screen.getByRole("cell", { name: "hi" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Pin this data" }));
    const pinned = store.getState().graph as WorkflowGraph;
    expect(pinned.nodes[1]?.pinned_output).toEqual({ echoed: "hi" });
    rerender(
      <OutputPane
        workflowId="wf"
        catalog={[STEP]}
        graph={pinned}
        node={pinned.nodes[1] as NodeInstance}
        definition={STEP}
      />,
    );
    expect(screen.getByText(/Pinned: test runs hand this on/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect((screen.getByLabelText("Pinned data as JSON") as HTMLTextAreaElement).value).toContain(
      '"echoed": "hi"',
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Unpin" }));
    expect(store.getState().graph?.nodes[1]?.pinned_output).toBeNull();
  });

  it("shows why the step failed last time", () => {
    seed(line());
    store.getState().mergeStepData({
      b: { output: null, error: { code: "BAD", message: "It broke" }, runId: "r" },
    });
    renderOutput();
    expect(screen.getByText("BAD: It broke")).toBeTruthy();
    expect(screen.queryByText(/No output yet/)).toBeNull();
  });

  it("offers no pinning on a step that decides the route", () => {
    seed(line({ definition_id: "logic.if" }));
    renderOutput(DECIDE, [STEP, DECIDE]);
    expect(screen.queryByRole("button", { name: "Write data to pin" })).toBeNull();
  });

  it("tests the step on what the steps before it handed on, and follows its run", async () => {
    seed(line());
    store.getState().mergeStepData({
      a: { output: { echoed: "hi", payload: { name: "Ada" } }, error: null, runId: "r" },
    });
    renderOutput();

    await userEvent.click(screen.getByRole("button", { name: "Test step" }));

    expect(mutate).toHaveBeenCalledWith(
      {
        workflow_id: "wf",
        mode: "test",
        input: { name: "Ada" },
        step: { node_id: "b", outputs: { a: { echoed: "hi", payload: { name: "Ada" } } } },
      },
      expect.anything(),
    );
    expect(store.getState().watchedRunId).toBe("run-2");
    expect(store.getState().testingNodeId).toBe("b");
  });

  it("asks before testing a step that writes, and starts with the trigger's sample", async () => {
    seed(line());
    renderOutput(WRITER, [WRITER]);

    await userEvent.click(screen.getByRole("button", { name: "Test step" }));
    expect(mutate).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getAllByRole("button", { name: "Test step" }).at(-1) as HTMLElement,
    );

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ input: {}, step: { node_id: "b", outputs: {} } }),
      expect.anything(),
    );
  });

  it("asks for the declared input when no earlier run says what it was", async () => {
    const trigger: NodeInstance = {
      ...node("t", "trigger.manual"),
      config: { fields: [{ name: "email", type: "text", required: true }] },
    };
    seed(line({}, trigger));
    renderOutput(STEP, [MANUAL, STEP]);

    await userEvent.click(screen.getByRole("button", { name: "Test step" }));

    expect(mutate).not.toHaveBeenCalled();
    const dialog = within(screen.getByRole("dialog"));
    await userEvent.type(dialog.getByRole("textbox"), "ada@example.com");
    await userEvent.click(dialog.getByRole("button", { name: "Start a run" }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ input: { email: "ada@example.com" } }),
      expect.anything(),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cannot test a step inside a loop, a draft with problems or one still saving", () => {
    const looped = {
      ...line(),
      scopes: [
        {
          scope_node_id: "a",
          body_node_ids: ["b"],
          entry_port: "body",
          exit_node_id: "a",
          exit_port: "done",
        },
      ],
    };
    seed(looped);
    const { unmount } = renderOutput();
    expect(screen.getByRole("button", { name: "Test step" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test step" })).toHaveAttribute(
      "title",
      "A step inside a loop runs once per item; test the loop instead",
    );
    unmount();

    seed(line({ definition_id: "gone.step" }));
    const second = renderOutput();
    expect(screen.getByRole("button", { name: "Test step" }).getAttribute("title")).toMatch(
      /problem/,
    );
    second.unmount();

    seed(line());
    store.getState().markDirty();
    renderOutput();
    expect(screen.getByRole("button", { name: "Test step" })).toBeDisabled();
  });

  it("shows the test as running until its run ends", () => {
    seed(line());
    store.getState().watchRun("run-3", "b");
    renderOutput();
    expect(screen.getByRole("button", { name: "Test step" })).toBeDisabled();
  });
});
