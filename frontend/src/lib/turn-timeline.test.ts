import { describe, expect, it } from "vitest";
import type { MessagePart, ToolCall } from "@/types";
import { canonicalParts, groupWorkParts, mergeToolCall, runsOf } from "./turn-timeline";
import { useChatStore } from "@/stores/chat-store";
import { conversationMessageToChatMessage } from "./conversation-to-chat";
const tool = (
  id: string,
  status: ToolCall["status"] = "running",
  name = "read_file",
): ToolCall => ({ id, name, status, args: { path: id } });
const part = (call: ToolCall, id = call.id): MessagePart => ({ id, type: "tool", toolCall: call });
describe("one timeline for live frames and stored turns", () => {
  it("updates a repeated call in place without collapsing distinct identical calls", () => {
    const duplicateText: MessagePart = { id: "text", type: "text", content: "old" };
    expect(canonicalParts([duplicateText, { ...duplicateText, content: "new" }])).toEqual([
      { ...duplicateText, content: "new" },
    ]);
    const first = tool("a");
    const result = canonicalParts([
      part(first, "temporary"),
      part(tool("b")),
      part({ ...first, status: "completed", result: "read" }, "replayed"),
    ]);
    expect(result.map((item) => item.id)).toEqual(["temporary", "b"]);
    expect(result[0]?.toolCall?.result).toBe("read");
  });
  it("does not regress a terminal call when a delayed opening frame arrives", () => {
    const completed = { ...tool("a", "completed"), result: "done" };
    expect(mergeToolCall(completed, tool("a", "pending"))).toEqual(completed);
    expect(mergeToolCall(completed, { status: "running" })).toEqual(completed);
    expect(mergeToolCall(completed, { name: "renamed" }).name).toBe("renamed");
    expect(mergeToolCall(completed, { status: "completed", result: undefined }).result).toBe(
      "done",
    );
    expect(
      mergeToolCall(tool("a", "awaiting_answer"), { status: "completed", result: "yes" }).result,
    ).toBe("yes");
  });
  it("keeps prose and questions outside routine work in both representations", () => {
    const question = {
      ...tool("q", "awaiting_answer", "ask_user_question"),
      args: { questions: [{ question: "Format?" }] },
    };
    const live = [
      part(tool("a")),
      { id: "text", type: "text", content: "Choose a format." } satisfies MessagePart,
      part(question),
    ];
    const saved = conversationMessageToChatMessage({
      id: "m",
      conversation_id: "c",
      role: "assistant",
      content: "Choose a format.",
      created_at: "2026-11-21T08:00:00Z",
      run_status: "awaiting_answer",
      parts: [
        { type: "tool", tool_call_id: "a" },
        { type: "text", text: "Choose a format." },
        { type: "tool", tool_call_id: "q" },
      ],
      tool_calls: [tool("a"), question].map((call) => ({
        tool_call_id: call.id,
        tool_name: call.name,
        status: call.status,
        args: call.args,
      })),
    });
    expect(groupWorkParts(runsOf(live)).map((group) => group.kind)).toEqual([
      "work",
      "visible",
      "visible",
    ]);
    expect(groupWorkParts(runsOf(saved.parts ?? [])).map((group) => group.kind)).toEqual([
      "work",
      "visible",
      "visible",
    ]);
  });
  it("keeps the store's timeline and call index in sync across repeated frames", () => {
    useChatStore.setState({
      messages: [{ id: "m", role: "assistant", content: "", timestamp: new Date() }],
    });
    const store = useChatStore.getState();
    store.addToolCallPart("m", tool("a", "pending"));
    store.addToolCallPart("m", tool("a", "running"));
    store.updateToolCallPart("m", "a", { status: "completed", result: "done" });
    store.addToolCallPart("m", tool("a", "pending"));
    const message = useChatStore.getState().messages[0]!;
    expect(message.parts).toHaveLength(1);
    expect(message.toolCalls).toHaveLength(1);
    expect(message.parts?.[0]?.toolCall).toEqual(message.toolCalls?.[0]);
    expect(message.toolCalls?.[0]?.status).toBe("completed");
    useChatStore.getState().clearMessages();
  });
  it("keeps consecutive delegated questions in one receipt", () => {
    const runs = runsOf([
      { id: "q1", type: "ask_user", question: "Format?", answer: "List" },
      { id: "q2", type: "ask_user", question: "Length?", answer: "Short" },
    ]);
    expect(runs).toHaveLength(1);
    expect(runs[0]?.kind === "other" && runs[0].questionParts).toHaveLength(2);
  });
});
