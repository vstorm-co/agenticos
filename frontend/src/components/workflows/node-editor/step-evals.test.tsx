import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EvalCase, EvalRun, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import { StepEvals } from "./step-evals";

const state = vi.hoisted(() => ({
  cases: [] as EvalCase[],
  latest: null as EvalRun | null,
  isLoading: false,
  stepData: {} as Record<string, { output: Record<string, unknown> | null }>,
  create: vi.fn(),
  remove: vi.fn(),
  run: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  useStepEvals: () => ({
    cases: state.cases,
    latest: state.latest,
    isLoading: state.isLoading,
    create: { mutate: state.create, isPending: false },
    remove: { mutate: state.remove, isPending: false },
    run: { mutate: state.run, isPending: false },
  }),
}));
vi.mock("@/stores/workflow-editor-store", () => ({
  useWorkflowEditorStore: (pick: (store: { stepData: unknown }) => unknown) =>
    pick({ stepData: state.stepData }),
}));

const TRIGGER = "t1";
const ASK = "a1";
const graph = {
  entry_node_id: TRIGGER,
  nodes: [
    { id: TRIGGER, definition_id: "trigger.manual" },
    { id: ASK, definition_id: "ai.classify" },
  ],
  edges: [
    {
      id: "e",
      source_node_id: TRIGGER,
      source_port: "out",
      target_node_id: ASK,
      target_port: "in",
    },
  ],
  bindings: [],
} as unknown as WorkflowGraph;
const node = graph.nodes[1] as NodeInstance;

const refund: EvalCase = {
  id: "c1",
  node_instance_id: ASK,
  created_at: null,
  name: "Refund",
  run_input: {},
  outputs: {},
  expectation: { kind: "equals", field: "category", value: "billing" },
};

function renderEvals() {
  return render(<StepEvals workflowId="wf" graph={graph} node={node} />);
}

beforeEach(() => {
  state.cases = [];
  state.latest = null;
  state.isLoading = false;
  state.stepData = {};
  vi.clearAllMocks();
});

describe("StepEvals", () => {
  it("asks for a test before a case can be written, and has nothing to try", () => {
    renderEvals();

    expect(screen.getByText(/No case yet/)).toBeVisible();
    expect(screen.getByText(/test it once first/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Add a case" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Try the cases" })).toBeDisabled();
  });

  it("writes a case from the step's last test input", async () => {
    state.stepData = {
      [TRIGGER]: { output: { payload: { message: "money back" }, triggered_by: "api" } },
    };
    renderEvals();

    await userEvent.click(screen.getByRole("button", { name: "Add a case" }));
    await userEvent.type(screen.getByLabelText("Name"), " Refund ");
    fireEvent.change(screen.getByLabelText("Where in the answer"), {
      target: { value: "category" },
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Should" }));
    await userEvent.click(screen.getByRole("option", { name: "equals" }));
    await userEvent.type(screen.getByLabelText("Value"), "billing");
    await userEvent.click(screen.getByRole("button", { name: "Add the case" }));

    expect(state.create).toHaveBeenCalledWith(
      {
        name: "Refund",
        expectation: { kind: "equals", field: "category", value: "billing" },
        outputs: { [TRIGGER]: { payload: { message: "money back" }, triggered_by: "api" } },
        run_input: { message: "money back" },
      },
      expect.anything(),
    );
    state.create.mock.calls[0]![1].onSuccess();
  });

  it("takes an empty path as the whole output, and can be cancelled", async () => {
    state.stepData = { [TRIGGER]: { output: { triggered_by: "api" } } };
    renderEvals();

    await userEvent.click(screen.getByRole("button", { name: "Add a case" }));
    await userEvent.type(screen.getByLabelText("Name"), "Any");
    await userEvent.clear(screen.getByLabelText("Where in the answer"));
    await userEvent.type(screen.getByLabelText("Value"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Add the case" }));
    expect(state.create.mock.calls[0]![0]).toMatchObject({
      expectation: { kind: "contains", field: null, value: "x" },
      run_input: {},
    });

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("shows each case's verdict from the latest try, and tries them again", async () => {
    state.cases = [
      refund,
      {
        ...refund,
        id: "c2",
        name: "Bug",
        expectation: { kind: "contains", field: null, value: "eng" },
      },
      { ...refund, id: "c3", name: "Spam" },
      { ...refund, id: "c4", name: "Late" },
    ];
    state.latest = {
      id: "r1",
      node_instance_id: ASK,
      created_at: null,
      passed: 1,
      failed: 2,
      pending: 0,
      cost_usd: 0.0021,
      results: [
        {
          eval_id: "c1",
          name: "Refund",
          workflow_run_id: "run1",
          status: "succeeded",
          passed: true,
          actual: "billing",
          reason: null,
          cost_usd: 0.001,
        },
        {
          eval_id: "c2",
          name: "Bug",
          workflow_run_id: "run2",
          status: "succeeded",
          passed: false,
          actual: "",
          reason: null,
          cost_usd: 0.001,
        },
        {
          eval_id: "c3",
          name: "Spam",
          workflow_run_id: null,
          status: "refused",
          passed: false,
          actual: null,
          reason: "Budget spent",
          cost_usd: 0,
        },
      ],
    };
    renderEvals();

    expect(screen.getByText("1 of 3 passed")).toBeVisible();
    expect(screen.getByText("$0.0021")).toBeVisible();
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]!).getByLabelText("Passed")).toBeVisible();
    expect(within(rows[0]!).getByText("category equals “billing”")).toBeVisible();
    expect(within(rows[0]!).getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/workflows/wf/runs/run1",
    );
    expect(within(rows[1]!).getByLabelText("Failed")).toBeVisible();
    expect(within(rows[1]!).getByText("The whole output contains “eng”")).toBeVisible();
    expect(within(rows[1]!).getByText("Said: nothing")).toBeVisible();
    expect(within(rows[2]!).getByText("Budget spent")).toBeVisible();
    expect(within(rows[3]!).queryByLabelText(/Passed|Failed|Still running/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Try 4 cases" }));
    expect(state.run).toHaveBeenCalled();
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Remove Refund" }));
    expect(state.remove).toHaveBeenCalledWith("c1");
  });

  it("holds the next try while one is running, and says how many", () => {
    state.cases = [refund];
    state.latest = {
      id: "r1",
      node_instance_id: ASK,
      created_at: null,
      passed: 0,
      failed: 0,
      pending: 1,
      cost_usd: 0,
      results: [
        {
          eval_id: "c1",
          name: "Refund",
          workflow_run_id: "run1",
          status: "running",
          passed: null,
          actual: null,
          reason: null,
          cost_usd: 0,
        },
      ],
    };
    renderEvals();

    expect(screen.getByText("1 still running")).toBeVisible();
    expect(screen.getByLabelText("Still running")).toBeVisible();
    expect(screen.getByRole("button", { name: "Try 1 case" })).toBeDisabled();
  });

  it("draws no list while the cases load", () => {
    state.isLoading = true;
    renderEvals();
    expect(screen.queryByText(/No case yet/)).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
