import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { RunButton } from "./run-button";

const mutate = vi.fn();
const start = { mutate, isPending: false };
vi.mock("@/hooks", () => ({ useWorkflowRuns: () => ({ start }) }));

const store = useWorkflowEditorStore;
const MANUAL = makeDefinition({
  id: "trigger.manual",
  category: "triggers",
  ports: [port("out", "output", null)],
});
const CATALOG = [MANUAL];

function seed(config: Record<string, unknown> = {}, definitionId = "trigger.manual") {
  const node: NodeInstance = {
    id: "t",
    definition_id: definitionId,
    definition_version: 1,
    config,
    layout: { x: 0, y: 0 },
  };
  store
    .getState()
    .seedGraph({ entry_node_id: "t", nodes: [node], edges: [], bindings: [], scopes: [] });
}

beforeEach(() => {
  mutate.mockReset();
  mutate.mockImplementation((_body, options) => options?.onSuccess?.({ id: "run-1" }));
});
afterEach(() => store.getState().teardown());

describe("RunButton", () => {
  it("starts a test run of the draft at once, and on Ctrl or Cmd + Enter", async () => {
    seed();
    const onStarted = vi.fn();
    render(<RunButton workflowId="wf" catalog={CATALOG} onStarted={onStarted} />);

    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(mutate).toHaveBeenCalledWith(
      { workflow_id: "wf", mode: "test", input: {} },
      expect.anything(),
    );
    expect(onStarted).toHaveBeenCalledWith("run-1");
    expect(store.getState().watchedRunId).toBe("run-1");

    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(mutate).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(window, { key: "Enter" });
    expect(mutate).toHaveBeenCalledTimes(2);
    // A field that took Ctrl+Enter for itself - saving a description - does not run.
    const taken = new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, cancelable: true });
    taken.preventDefault();
    window.dispatchEvent(taken);
    expect(mutate).toHaveBeenCalledTimes(2);
  });

  it("asks for the declared fields first", async () => {
    seed({ fields: [{ name: "email", type: "text" }] });
    render(<RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("email"), { target: { value: "ada@example.com" } });
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(mutate).toHaveBeenCalledWith(
      { workflow_id: "wf", mode: "test", input: { email: "ada@example.com" } },
      expect.anything(),
    );
  });

  it("says why it cannot run: no steps, problems, or an edit still saving", () => {
    const { rerender } = render(
      <RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run" }).getAttribute("title")).toBe(
      "Add a step first",
    );

    seed({}, "gone.step");
    rerender(<RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Run" }).getAttribute("title")).toMatch(/Fix/);

    seed();
    store.setState({ isDirty: true });
    rerender(<RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    expect(mutate).not.toHaveBeenCalled();
    expect(store.getState().problemsRevealed).toBe(true);
  });
});
