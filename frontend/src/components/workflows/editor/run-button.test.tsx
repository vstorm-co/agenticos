import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { RunButton } from "./run-button";

const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
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
  it("opens the real form preview instead of testing sample answers", async () => {
    seed({ fields: [{ name: "name", type: "text" }] }, "trigger.form");
    const form = makeDefinition({
      id: "trigger.form",
      category: "triggers",
      ports: [port("out", "output", null)],
    });
    render(<RunButton workflowId="wf" catalog={[form]} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Test draft" }));
    expect(router.push).toHaveBeenCalledWith("/workflows/wf/form-preview?entry=t");
    expect(mutate).not.toHaveBeenCalled();
  });
  it("opens chat and waits for a real message", async () => {
    seed({}, "trigger.chat");
    const chat = makeDefinition({
      id: "trigger.chat",
      category: "triggers",
      ports: [port("out", "output", null)],
    });
    render(<RunButton workflowId="wf" catalog={[chat]} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Test draft" }));
    expect(screen.getByRole("textbox", { name: "Message" })).toBeVisible();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("starts a test run of the draft at once, and on Ctrl or Cmd + Enter", async () => {
    seed();
    const onStarted = vi.fn();
    render(<RunButton workflowId="wf" catalog={CATALOG} onStarted={onStarted} />);

    // It says it runs the draft, so a published workflow's builder does not
    // mistake it for a run of the live version.
    expect(screen.getByRole("button", { name: "Test draft" }).getAttribute("title")).toMatch(
      /not the published version/,
    );
    await userEvent.click(screen.getByRole("button", { name: "Test draft" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Test draft" }));
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
    expect(screen.getByRole("button", { name: "Test draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test draft" }).getAttribute("title")).toBe(
      "Add a step first",
    );

    seed({}, "gone.step");
    rerender(<RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Test draft" }).getAttribute("title")).toMatch(/Fix/);

    seed();
    store.setState({ isDirty: true });
    rerender(<RunButton workflowId="wf" catalog={CATALOG} onStarted={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Test draft" })).toBeDisabled();
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
    expect(mutate).not.toHaveBeenCalled();
    expect(store.getState().problemsRevealed).toBe(true);
  });
});

it("offers independent starts and sends the selected entry", async () => {
  seed();
  const graph = store.getState().graph!;
  const webhook = {
    ...graph.nodes[0]!,
    id: "hook",
    definition_id: "trigger.webhook",
    label: "Incoming request",
  };
  store.getState().seedGraph({ ...graph, nodes: [...graph.nodes, webhook] });
  const definition = makeDefinition({
    id: "trigger.webhook",
    category: "triggers",
    ports: [port("out", "output", null)],
  });
  render(<RunButton workflowId="wf" catalog={[...CATALOG, definition]} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Test draft" }));
  expect(mutate).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("combobox", { name: "Start from" }));
  await userEvent.click(screen.getByRole("option", { name: "Incoming request" }));
  await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
  expect(mutate).toHaveBeenCalledWith(
    expect.objectContaining({ entry_node_id: "hook", input: { body: {}, delivery_id: "test" } }),
    expect.anything(),
  );
});
