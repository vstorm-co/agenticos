import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunRead } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ChatPanel } from "./chat-panel";

const mutate = vi.fn();
const start = { mutate, isPending: false };
const runs = new Map<string, Partial<WorkflowRunRead> | null>();
vi.mock("@/hooks", () => ({
  useWorkflowRuns: () => ({ start }),
  useWorkflowRun: (runId: string) => ({ run: runs.get(runId) ?? null }),
}));

let next = 0;
beforeEach(() => {
  mutate.mockReset();
  runs.clear();
  next = 0;
  mutate.mockImplementation((_body, options) => options.onSuccess({ id: `run-${++next}` }));
});
afterEach(() => useWorkflowEditorStore.getState().teardown());

async function say(text: string) {
  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), `${text}{Enter}`);
}

describe("ChatPanel", () => {
  it("runs the draft as a test with each message, and opens the run", async () => {
    const onStarted = vi.fn();
    render(<ChatPanel workflowId="wf" blocked={null} onStarted={onStarted} />);

    await say("Hello");
    await say("Again");

    const [first] = mutate.mock.calls[0]!;
    const [second] = mutate.mock.calls[1]!;
    expect(first).toMatchObject({ workflow_id: "wf", mode: "test", input: { prompt: "Hello" } });
    // One conversation id for the whole chat, and no reply target of any kind.
    expect(second.input.conversation_id).toBe(first.input.conversation_id);
    expect(Object.keys(first)).toEqual(["workflow_id", "mode", "input"]);
    expect(onStarted).toHaveBeenLastCalledWith("run-2");
    expect(useWorkflowEditorStore.getState().watchedRunId).toBe("run-2");
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
  });

  it("shows each answer, a failure, a run still going and a run with nothing to say", async () => {
    render(<ChatPanel workflowId="wf" blocked={null} onStarted={vi.fn()} />);
    runs.set("run-1", { status: "succeeded", error: null, output: { text: "Hi there" } });
    runs.set("run-2", {
      status: "failed",
      error: { code: "X", message: "It broke" },
      output: null,
    });
    runs.set("run-3", { status: "running", error: null, output: null });
    runs.set("run-4", { status: "succeeded", error: null, output: null });
    for (const text of ["one", "two", "three", "four"]) await say(text);

    expect(screen.getByText("Hi there")).toBeInTheDocument();
    expect(screen.getByText("It broke")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/ended without an answer/)).toBeInTheDocument();
  });

  it("sends nothing blank or blocked, and a new chat starts over", async () => {
    const { rerender } = render(
      <ChatPanel workflowId="wf" blocked="Fix 1 problem" onStarted={vi.fn()} />,
    );
    expect(screen.getByText("Fix 1 problem")).toBeInTheDocument();
    await say("Hello");
    expect(mutate).not.toHaveBeenCalled();

    rerender(<ChatPanel workflowId="wf" blocked={null} onStarted={vi.fn()} />);
    await userEvent.clear(screen.getByRole("textbox", { name: "Message" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "   {Enter}");
    expect(mutate).not.toHaveBeenCalled();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Message" }),
      "line{Shift>}{Enter}{/Shift}two",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    const conversation = mutate.mock.calls[0]![0].input.conversation_id;

    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByText(/Send a message to run the draft/)).toBeInTheDocument();
    await say("Fresh");
    expect(mutate.mock.calls[1]![0].input.conversation_id).not.toBe(conversation);
  });
});
