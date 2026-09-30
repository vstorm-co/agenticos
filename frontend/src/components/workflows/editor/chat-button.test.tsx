import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeDefinition, node, port } from "@/components/workflows/validation/fixtures";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ChatButton } from "./chat-button";

vi.mock("./chat-panel", () => ({
  ChatPanel: ({ blocked }: { blocked: string | null }) => (
    <div data-testid="chat-panel">{blocked ?? "ready"}</div>
  ),
}));

const CHAT = makeDefinition({
  id: "trigger.chat",
  category: "triggers",
  ports: [port("out", "output", null)],
});
const MANUAL = makeDefinition({
  id: "trigger.manual",
  category: "triggers",
  ports: [port("out", "output", null)],
});

function seed(definitionId: string) {
  const graph: WorkflowGraph = {
    entry_node_id: "t",
    nodes: [node("t", definitionId)],
    edges: [],
    bindings: [],
    scopes: [],
  };
  useWorkflowEditorStore.getState().seedGraph(graph);
}

afterEach(() => useWorkflowEditorStore.getState().teardown());

describe("ChatButton", () => {
  it("opens the chat for a draft that starts from a chat message", async () => {
    seed("trigger.chat");
    render(<ChatButton workflowId="wf" catalog={[CHAT]} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Open chat" }));
    expect(screen.getByTestId("chat-panel")).toHaveTextContent("ready");
    await userEvent.click(screen.getByRole("button", { name: "Close the chat" }));
    expect(screen.queryByTestId("chat-panel")).toBeNull();
  });

  it("is not offered for a draft that starts another way, or has none", () => {
    seed("trigger.manual");
    const { rerender } = render(
      <ChatButton workflowId="wf" catalog={[MANUAL]} onStarted={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Open chat" })).toBeNull();
    useWorkflowEditorStore.getState().teardown();
    rerender(<ChatButton workflowId="wf" catalog={[MANUAL]} onStarted={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Open chat" })).toBeNull();
  });

  it("holds messages back while the draft has problems or is saving", async () => {
    seed("trigger.chat");
    const { rerender } = render(<ChatButton workflowId="wf" catalog={[]} onStarted={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Open chat" }));
    expect(screen.getByTestId("chat-panel")).not.toHaveTextContent("ready");

    useWorkflowEditorStore.setState({ isDirty: true });
    rerender(<ChatButton workflowId="wf" catalog={[CHAT]} onStarted={vi.fn()} />);
    expect(screen.getByTestId("chat-panel")).not.toHaveTextContent("ready");
  });
});
