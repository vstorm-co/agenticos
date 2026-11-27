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
  it("folds intermediate browser narration with its work while preserving the final answer", () => {
    const runs = runsOf([
      { id: "intro", type: "text", content: "Opening the browser." },
      part(tool("open", "completed", "browser_open")),
      { id: "progress", type: "text", content: "Reading the page." },
      part(tool("read", "completed", "browser_read")),
      { id: "answer", type: "text", content: "The page is open." },
    ]);
    const groups = groupWorkParts(runs, { foldProgress: true });
    expect(groups.map((group) => group.kind)).toEqual(["work", "visible"]);
    expect(groups[0]?.kind === "work" && groups[0].runs).toEqual(runs.slice(0, 4));
    expect(groups[1]).toEqual({ kind: "visible", run: runs[4] });
  });
  it("never folds questions, handoffs or their preceding explanation into later browser work", () => {
    const question = part(tool("question", "awaiting_answer", "ask_user_question"));
    const runs = runsOf([
      part(tool("open", "completed", "browser_open")),
      { id: "explain", type: "text", content: "Choose whether to continue." },
      question,
      { id: "steer", type: "steer", content: "Use the second tab." },
      { id: "resume", type: "text", content: "Reading the second tab." },
      part(tool("read", "completed", "browser_read")),
      { id: "answer", type: "text", content: "Finished." },
    ]);
    const groups = groupWorkParts(runs, { foldProgress: true });
    expect(groups.map((group) => group.kind)).toEqual([
      "work",
      "visible",
      "visible",
      "visible",
      "work",
      "visible",
    ]);
    expect(groups[4]?.kind === "work" && groups[4].runs).toEqual(runs.slice(4, 6));
  });
  it.each([false, true])(
    "retains an answered question while browser activity frames coalesce (args: %s)",
    (includeArgs) => {
      const args = { questions: [{ header: "Continue", question: "Open the page?" }] };
      const answered: ToolCall = {
        ...tool("question", "completed", "ask_user_question"),
        args,
        result: { Continue: ["Yes"] },
      };
      const updated = mergeToolCall(answered, { result: {}, ...(includeArgs ? { args } : {}) });
      expect(updated.result).toEqual({ Continue: ["Yes"] });
      const groups = groupWorkParts(
        runsOf([
          part(tool("open", "completed", "browser_open")),
          part(updated),
          part(tool("read", "completed", "browser_read")),
        ]),
        { foldProgress: true },
      );
      expect(groups.map((group) => group.kind)).toEqual(["work", "visible", "work"]);
    },
  );
  it("keeps consecutive delegated questions in one receipt", () => {
    const runs = runsOf([
      { id: "q1", type: "ask_user", question: "Format?", answer: "List" },
      { id: "q2", type: "ask_user", question: "Length?", answer: "Short" },
    ]);
    expect(runs).toHaveLength(1);
    expect(runs[0]?.kind === "other" && runs[0].questionParts).toHaveLength(2);
  });
});
