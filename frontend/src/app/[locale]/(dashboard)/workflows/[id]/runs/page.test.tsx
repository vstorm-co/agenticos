import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";

import WorkflowRunsPage from "./page";

const state = vi.hoisted(() => ({
  canTest: false,
  version: undefined as { graph: WorkflowGraph } | undefined,
  error: null as Error | null,
  admissionError: null as Error | null,
  mutate: vi.fn(),
  reset: vi.fn(),
  refetch: vi.fn(),
  inputErrorsInForm: false,
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({ actions }: { actions: React.ReactNode }) => <header>{actions}</header>,
}));
vi.mock("@/components/workflows/runs/run-history", () => ({ RunHistory: () => null }));
vi.mock("@/components/workflows/runs/workflow-stats", () => ({ WorkflowStats: () => null }));
vi.mock("@/hooks", () => ({
  useWorkflow: () => ({
    workflow: {
      id: "wf",
      name: "Workflow",
      current_version_id: "v1",
      status: "published",
      live_trigger: "trigger.manual",
      draft_graph: null,
    },
  }),
  usePermissions: () => ({
    can: (permission: string) =>
      permission === Perm.workflowsRun || (state.canTest && permission === Perm.workflowsEdit),
  }),
  useWorkflowRuns: (_id: string, inForm: boolean) => {
    state.inputErrorsInForm = inForm;
    return {
      start: {
        mutate: state.mutate,
        reset: state.reset,
        error: state.admissionError,
        isPending: false,
      },
    };
  },
  useWorkflowVersion: () => ({
    version: state.version,
    error: state.error,
    isLoading: state.version === undefined && state.error === null,
    refetch: state.refetch,
  }),
}));

const GRAPH: WorkflowGraph = {
  entry_node_id: "live-entry",
  nodes: [
    {
      id: "live-entry",
      definition_id: "trigger.manual",
      definition_version: 1,
      config: {
        input_schema: {
          type: "object",
          required: ["items"],
          properties: { items: { type: "array", items: { type: "object" } } },
        },
      },
      layout: { x: 0, y: 0 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

beforeEach(() => {
  state.canTest = false;
  state.version = undefined;
  state.error = null;
  state.admissionError = null;
  state.inputErrorsInForm = false;
  state.mutate.mockReset();
  state.reset.mockReset();
  state.refetch.mockReset();
});

async function mount() {
  const params = Promise.resolve({ id: "wf" });
  const view = () => (
    <Suspense>
      <WorkflowRunsPage params={params} />
    </Suspense>
  );
  let rerender: (element: React.ReactNode) => void = () => undefined;
  await act(async () => {
    ({ rerender } = render(view()));
  });
  return () => rerender(view());
}

describe("Workflow runs input contract", () => {
  it("waits for the published contract before showing an executable input form", async () => {
    const rerender = await mount();
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(
      within(screen.getByRole("dialog")).queryByRole("button", { name: "Start a run" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Input (JSON)")).not.toBeInTheDocument();
    expect(state.mutate).not.toHaveBeenCalled();
    expect(state.inputErrorsInForm).toBe(false);

    state.version = { graph: GRAPH };
    rerender();
    const dialog = within(screen.getByRole("dialog"));
    expect(state.inputErrorsInForm).toBe(true);
    expect(dialog.getByRole("button", { name: "Expected input schema" })).toBeVisible();
    fireEvent.change(dialog.getByLabelText("Input (JSON)"), {
      target: { value: '{"items":[{"sku":"a"}]}' },
    });
    rerender();
    expect(dialog.getByLabelText("Input (JSON)")).toHaveValue('{"items":[{"sku":"a"}]}');
    await userEvent.click(dialog.getByRole("button", { name: "Start a run" }));
    expect(state.mutate).toHaveBeenCalledWith(
      {
        workflow_id: "wf",
        mode: "real",
        entry_node_id: "live-entry",
        input: { items: [{ sku: "a" }] },
      },
      expect.anything(),
    );
  });

  it("reports a failed published-contract lookup and offers a retry", async () => {
    state.error = new Error("Cannot load this published workflow");
    await mount();
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("alert")).toHaveTextContent("Cannot load this published workflow");
    expect(dialog.queryByRole("button", { name: "Start a run" })).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalledOnce();
    expect(state.mutate).not.toHaveBeenCalled();
    expect(state.inputErrorsInForm).toBe(false);
  });

  it("shows published-run admission field errors and clears them when the input changes", async () => {
    state.version = { graph: GRAPH };
    const rerender = await mount();
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    const dialog = within(screen.getByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Start a run" }));
    state.admissionError = new ApiError(422, "Input rejected", {
      error: {
        code: "WORKFLOW_RUN_INPUT_INVALID",
        message: "Input rejected",
        details: { fields: [{ field: "input.items", message: "Field required" }] },
      },
    });
    rerender();
    expect(dialog.getByRole("alert")).toHaveTextContent("input.items: Field required");
    fireEvent.change(dialog.getByLabelText("Input (JSON)"), { target: { value: '{"items":[]}' } });
    expect(state.reset).toHaveBeenCalledOnce();
  });
});
