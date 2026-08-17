import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStore } from "./chat-store";
import type { ChatMessage, ToolCall } from "@/types";

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "",
    timestamp: new Date("2026-07-31T12:00:00Z"),
    ...overrides,
  };
}

function toolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: "tc-1", name: "search_documents", args: {}, status: "pending", ...overrides };
}

const store = () => useChatStore.getState();

/** The parts of the message being streamed, as a readable timeline. */
function timeline(id = "m-1") {
  const found = store().messages.find((msg) => msg.id === id);
  return (found?.parts ?? []).map((part) => `${part.type}:${part.content ?? part.toolCall?.id}`);
}

/**
 * The message being streamed.
 *
 * A turn arrives as deltas, and this is what turns them into something ordered:
 * consecutive text extends the trailing part rather than starting a new bubble,
 * and a tool call between two sentences splits them, because that is the order
 * things happened in. Every part also carries a stable id, so React does not
 * reuse a rendered row for a different part when the next delta lands.
 *
 * The flat `content` and `toolCalls` aggregates are kept in step deliberately -
 * a saved conversation is reloaded from them, and a timeline that disagreed with
 * them would render differently after a refresh than it did live.
 */
beforeEach(() => {
  useChatStore.setState({ messages: [], isStreaming: false });
});

describe("the message list", () => {
  it("appends a message", () => {
    store().addMessage(message({ id: "m-1" }));
    store().addMessage(message({ id: "m-2" }));

    expect(store().messages.map((msg) => msg.id)).toEqual(["m-1", "m-2"]);
  });

  it("updates the message with the given id and leaves the others alone", () => {
    store().addMessage(message({ id: "m-1", content: "a" }));
    store().addMessage(message({ id: "m-2", content: "b" }));

    store().updateMessage("m-2", (msg) => ({ ...msg, content: "changed" }));

    expect(store().messages.map((msg) => msg.content)).toEqual(["a", "changed"]);
  });

  it("updates every message a predicate matches, which is how a rating lands", () => {
    // A rating arrives keyed by conversation and message, and the store is asked
    // for "whichever message this is" rather than for an index.
    store().addMessage(message({ id: "m-1", role: "user" }));
    store().addMessage(message({ id: "m-2" }));

    store().updateMessagesWhere(
      (msg) => msg.role === "assistant",
      (msg) => ({ ...msg, user_rating: 1 }),
    );

    expect(store().messages.map((msg) => msg.user_rating)).toEqual([undefined, 1]);
  });

  it("clears the messages without touching the streaming flag", () => {
    // Starting a new conversation mid-stream is reachable; the flag belongs to
    // the request, not to the list.
    store().addMessage(message());
    store().setStreaming(true);

    store().clearMessages();

    expect(store().messages).toEqual([]);
    expect(store().isStreaming).toBe(true);
  });

  it("says whether a turn is in flight", () => {
    store().setStreaming(true);
    expect(store().isStreaming).toBe(true);

    store().setStreaming(false);
    expect(store().isStreaming).toBe(false);
  });
});

describe("streaming text", () => {
  it("extends the trailing text part rather than starting a bubble per delta", () => {
    store().addMessage(message());

    store().appendTextDelta("m-1", "Refunds ");
    store().appendTextDelta("m-1", "run to thirty days.");

    expect(timeline()).toEqual(["text:Refunds run to thirty days."]);
    expect(store().messages[0]?.content).toBe("Refunds run to thirty days.");
  });

  it("starts a new text part after a tool call, because the order is the point", () => {
    store().addMessage(message());
    store().appendTextDelta("m-1", "Let me check. ");
    store().addToolCallPart("m-1", toolCall());

    store().appendTextDelta("m-1", "Thirty days.");

    expect(timeline()).toEqual(["text:Let me check. ", "tool:tc-1", "text:Thirty days."]);
    // The flat aggregate is the whole answer, without the tool between.
    expect(store().messages[0]?.content).toBe("Let me check. Thirty days.");
  });

  it("gives every part its own id, so a rendered row is never reused", () => {
    store().addMessage(message());
    store().appendTextDelta("m-1", "a");
    store().addToolCallPart("m-1", toolCall());
    store().appendTextDelta("m-1", "b");

    const ids = (store().messages[0]?.parts ?? []).map((part) => part.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("ignores a delta for a message that is not there", () => {
    // A stream frame can outlive the conversation somebody navigated away from.
    store().addMessage(message());

    store().appendTextDelta("m-gone", "orphan");

    expect(store().messages[0]?.content).toBe("");
  });
});

describe("streaming reasoning", () => {
  it("extends the trailing thinking part, and the flat aggregate with it", () => {
    store().addMessage(message());

    store().appendThinkingDelta("m-1", "Checking ");
    store().appendThinkingDelta("m-1", "the policy.");

    expect(timeline()).toEqual(["thinking:Checking the policy."]);
    expect(store().messages[0]?.thinking).toBe("Checking the policy.");
  });

  it("starts a new thinking part when something else came in between", () => {
    // A model that reasons, calls a tool, then reasons again.
    store().addMessage(message());
    store().appendThinkingDelta("m-1", "First.");
    store().addToolCallPart("m-1", toolCall());

    store().appendThinkingDelta("m-1", "Second.");

    expect(timeline()).toEqual(["thinking:First.", "tool:tc-1", "thinking:Second."]);
    expect(store().messages[0]?.thinking).toBe("First.Second.");
  });

  it("ignores a reasoning delta for a message that is not there", () => {
    store().addMessage(message());

    store().appendThinkingDelta("m-gone", "orphan");

    expect(store().messages[0]?.thinking).toBeUndefined();
  });
});

describe("tool calls", () => {
  it("adds a call to the flat list", () => {
    store().addMessage(message());

    store().addToolCall("m-1", toolCall());

    expect(store().messages[0]?.toolCalls).toHaveLength(1);
    expect(store().messages[0]?.parts).toBeUndefined();
  });

  it("adds a second call to a message that already has one", () => {
    store().addMessage(message({ toolCalls: [toolCall()] }));

    store().addToolCall("m-1", toolCall({ id: "tc-2" }));

    expect(store().messages[0]?.toolCalls?.map((tc) => tc.id)).toEqual(["tc-1", "tc-2"]);
  });

  it("adds a flat call only to the message it names", () => {
    store().addMessage(message({ id: "m-1" }));
    store().addMessage(message({ id: "m-2" }));

    store().addToolCall("m-2", toolCall());

    expect(store().messages[0]?.toolCalls).toBeUndefined();
    expect(store().messages[1]?.toolCalls).toHaveLength(1);
  });

  it("updates the call it names and leaves the others", () => {
    store().addMessage(message({ toolCalls: [toolCall(), toolCall({ id: "tc-2" })] }));

    store().updateToolCall("m-1", "tc-2", { status: "completed", result: "42" });

    expect(store().messages[0]?.toolCalls).toEqual([
      expect.objectContaining({ id: "tc-1", status: "pending" }),
      expect.objectContaining({ id: "tc-2", status: "completed", result: "42" }),
    ]);
  });

  it("ignores an update for a message or a call that is not there", () => {
    store().addMessage(message({ toolCalls: [toolCall()] }));

    store().updateToolCall("m-gone", "tc-1", { status: "completed" });
    store().updateToolCall("m-1", "tc-gone", { status: "completed" });

    expect(store().messages[0]?.toolCalls?.[0]?.status).toBe("pending");
  });

  it("adds a part only to the message it names", () => {
    // A tool call frame carries a message id, and the stream can be mid-turn on
    // one message while another is still on screen.
    store().addMessage(message({ id: "m-1" }));
    store().addMessage(message({ id: "m-2" }));

    store().addToolCallPart("m-2", toolCall());

    expect(store().messages[0]?.parts).toBeUndefined();
    expect(timeline("m-2")).toEqual(["tool:tc-1"]);
  });

  it("adds a call as a part and to the flat list at once", () => {
    // Both, because the timeline renders the live turn and the flat list is what
    // a reloaded conversation is rebuilt from.
    store().addMessage(message());

    store().addToolCallPart("m-1", toolCall());

    expect(timeline()).toEqual(["tool:tc-1"]);
    expect(store().messages[0]?.toolCalls).toHaveLength(1);
  });

  it("keeps a call's part and its flat entry in step when the result lands", () => {
    store().addMessage(message());
    store().addToolCallPart("m-1", toolCall());
    store().addToolCallPart("m-1", toolCall({ id: "tc-2" }));

    store().updateToolCallPart("m-1", "tc-2", { status: "completed", result: "42" });

    const parts = store().messages[0]?.parts ?? [];
    expect(parts[0]?.toolCall).toMatchObject({ id: "tc-1", status: "pending" });
    expect(parts[1]?.toolCall).toMatchObject({ id: "tc-2", status: "completed" });
    expect(store().messages[0]?.toolCalls?.[1]).toMatchObject({ status: "completed" });
  });

  it("leaves a text part alone while updating a tool one", () => {
    store().addMessage(message());
    store().appendTextDelta("m-1", "Let me check.");
    store().addToolCallPart("m-1", toolCall());

    store().updateToolCallPart("m-1", "tc-1", { status: "completed" });

    expect(timeline()).toEqual(["text:Let me check.", "tool:tc-1"]);
  });

  it("ignores a part update for a message that is not there", () => {
    store().addMessage(message());
    store().addToolCallPart("m-1", toolCall());

    store().updateToolCallPart("m-gone", "tc-1", { status: "completed" });

    expect(store().messages[0]?.parts?.[0]?.toolCall?.status).toBe("pending");
  });
});

describe("part ids on a runtime without randomUUID", () => {
  it("still gives each part its own id", async () => {
    // `crypto.randomUUID` needs a secure context. A page served over plain HTTP -
    // which is how this is deployed behind a proxy more often than not - has
    // `crypto` and no `randomUUID`, and two parts sharing an id makes React
    // render one of them twice. What `clientId` falls back to is pinned in
    // `lib/ids.test.ts`; what matters here is that the parts stay distinct.
    vi.stubGlobal("crypto", {});
    useChatStore.setState({ messages: [] });

    store().addMessage(message());
    store().appendTextDelta("m-1", "a");
    store().addToolCallPart("m-1", toolCall());

    const ids = (store().messages[0]?.parts ?? []).map((part) => part.id);
    expect(new Set(ids).size).toBe(2);

    vi.unstubAllGlobals();
  });
});
