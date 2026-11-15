import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatStore } from "./chat-store";
import type { TranscriptIdentity } from "./conversation-store";
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
  useChatStore.setState({ messages: [], isStreaming: false, loadedTranscript: null });
});

describe("committed transcript identity", () => {
  const identity: TranscriptIdentity = {
    conversationId: "room",
    selectionVersion: 1,
    accountId: "me",
    tenantId: "organization",
  };

  it("publishes a loaded empty transcript atomically and clears readiness with the messages", () => {
    const committed = vi.fn();
    const unsubscribe = useChatStore.subscribe(committed);
    store().rereadMessages([], identity);
    expect(committed).toHaveBeenCalledTimes(1);
    expect(committed.mock.calls[0]?.[0]).toMatchObject({
      messages: [],
      loadedTranscript: identity,
    });
    unsubscribe();
    store().clearMessages();
    expect(store().loadedTranscript).toBeNull();
  });

  it("keeps newer local and streaming messages when an empty refresh lands", () => {
    store().rereadMessages([], identity);
    store().addMessage(message({ id: "prompt", role: "user", isTemporaryId: true }));
    store().addMessage(message({ id: "answer", content: "New", isStreaming: true }));
    store().rereadMessages([], { ...identity });
    store().appendTextDelta("answer", " answer");
    expect(store().messages.map((item) => item.id)).toEqual(["prompt", "answer"]);
    expect(store().messages[1]?.content).toBe("New answer");
  });

  it("retains unresolved live content only for its successful concrete-tenant revalidation", () => {
    store().rereadMessages([], { ...identity, tenantId: null });
    store().addMessage(message({ id: "answer", content: "Live", isStreaming: true }));
    store().rereadMessages([], identity);
    expect(store().messages[0]?.content).toBe("Live");
    expect(store().loadedTranscript).toEqual(identity);
    store().rereadMessages([], { ...identity, tenantId: "other" });
    expect(store().messages).toEqual([]);
  });

  it.each([
    { conversationId: "another-room" },
    { selectionVersion: 2 },
    { accountId: "another-account" },
    { tenantId: "another-organization" },
  ])("does not retain another loaded identity's messages: %j", (changed) => {
    store().rereadMessages([], identity);
    store().addMessage(message({ id: "old", content: "Old session" }));
    const next = { ...identity, ...changed };
    store().rereadMessages([], next);
    expect(store().messages).toEqual([]);
    expect(store().loadedTranscript).toEqual(next);
  });
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

  it("starts a new text part when a new model response begins", () => {
    // #2108: a background tool answers as a message, with no tool step between.
    store().addMessage(message());
    store().appendTextDelta("m-1", "A haiku while it runs.");

    store().appendTextDelta("m-1", "The heading is Example Domain.", true);

    expect(timeline()).toEqual([
      "text:A haiku while it runs.",
      "text:The heading is Example Domain.",
    ]);
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

describe("the reply being written", () => {
  it("is chosen, and goes with the conversation it was chosen in", () => {
    const reply = { messageId: "m-1", role: "assistant" as const, excerpt: "x" };
    useChatStore.getState().setReplyTo(reply);
    expect(useChatStore.getState().replyTo).toEqual(reply);

    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().replyTo).toBeNull();
  });

  it("stays while the same conversation is read again", () => {
    const reply = { messageId: "m-1", role: "assistant" as const, excerpt: "x" };
    useChatStore.getState().addMessage({
      id: "m-1",
      role: "assistant",
      content: "x",
      timestamp: new Date(),
    });
    useChatStore.getState().setReplyTo(reply);

    useChatStore.getState().rereadMessages();

    expect(useChatStore.getState().messages).toEqual([]);
    expect(useChatStore.getState().replyTo).toEqual(reply);
  });
});

describe("reconciling a late transcript", () => {
  it("keeps a later streaming turn addressable by subsequent deltas", () => {
    store().addMessage(message({ id: "first", content: "saved" }));
    store().addMessage(
      message({ id: "next-user", role: "user", content: "next", isTemporaryId: true }),
    );
    store().addMessage(
      message({ id: "next", content: "stream", isTemporaryId: true, isStreaming: true }),
    );
    store().rereadMessages([message({ id: "first", content: "saved" })]);
    store().appendTextDelta("next", " continues");
    expect(store().messages.map((item) => item.id)).toEqual(["first", "next-user", "next"]);
    expect(store().messages.at(-1)?.content).toBe("stream continues");
  });

  it("keeps an unsaved answer and its error while replacing the persisted prefix", () => {
    store().addMessage(message({ id: "question", role: "user" }));
    store().addMessage(
      message({ id: "unsaved", content: "Answer\nCould not save", isTemporaryId: true }),
    );
    store().rereadMessages([message({ id: "question", role: "user" })]);
    expect(store().messages.at(-1)?.content).toBe("Answer\nCould not save");
  });
});

it("does not truncate a live persisted bubble or remount a saved one on a stale read", () => {
  store().addMessage(message({ id: "saved", content: "saved", renderKey: "original" }));
  store().addMessage(message({ id: "live", content: "new deltas", isStreaming: true }));
  store().rereadMessages([
    message({ id: "saved", content: "saved" }),
    message({ id: "live", content: "old deltas" }),
  ]);
  expect(store().messages[0]?.renderKey).toBe("original");
  expect(store().messages[1]?.content).toBe("new deltas");
});

function submitted(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return message({
    id: "local-question",
    role: "user",
    content: "repeat",
    isTemporaryId: true,
    clientMessageId: "nonce",
    conversationId: "conversation",
    sender: { user_id: "me", name: "Me", has_avatar: false, avatar_color: null },
    ...overrides,
  });
}

it("reconciles a persisted prompt and answer when the acknowledgement was lost", () => {
  store().addMessage(submitted());
  store().addMessage(message({ id: "local-answer", content: "partial", isTemporaryId: true }));
  store().rereadMessages([
    submitted({ id: "saved-question", isTemporaryId: false }),
    message({ id: "saved-answer", content: "finished" }),
  ]);
  expect(store().messages.map((item) => item.id)).toEqual(["saved-question", "saved-answer"]);
  expect(store().messages[0]?.renderKey).toBe("local-question");
  expect(store().messages[1]?.content).toBe("finished");
});

it("keeps a live reconciled answer addressable across repeated transcript reads", () => {
  store().addMessage(submitted());
  store().addMessage(
    message({
      id: "live",
      content: "stream",
      isStreaming: true,
      isTemporaryId: true,
      runId: "run",
    }),
  );
  const history = [
    submitted({ id: "saved-question", isTemporaryId: false }),
    message({ id: "saved-answer", content: "old", runId: "run" }),
  ];
  store().rereadMessages(history);
  store().appendTextDelta("live", " continues");
  store().rereadMessages(history);
  expect(store().messages.map((item) => item.id)).toEqual(["saved-question", "live"]);
  expect(store().messages[1]?.content).toBe("stream continues");
});

it.each([
  { clientMessageId: "later-nonce" },
  { conversationId: "another-conversation" },
  { sender: { user_id: "other", name: "Other", has_avatar: false, avatar_color: null } },
  { clientMessageId: undefined },
])("keeps a different submission even when its text repeats: %j", (difference) => {
  store().addMessage(submitted(difference));
  store().rereadMessages([submitted({ id: "saved-question", isTemporaryId: false })]);
  expect(store().messages.map((item) => item.id)).toEqual(["saved-question", "local-question"]);
});

it("preserves an unsaved answer and error when only its correlated prompt was saved", () => {
  store().addMessage(submitted());
  store().addMessage(
    message({ id: "unsaved", content: "Result\nCould not save", isTemporaryId: true }),
  );
  store().rereadMessages([submitted({ id: "saved-question", isTemporaryId: false })]);
  expect(store().messages.at(-1)?.content).toBe("Result\nCould not save");
});

it.each([
  { responses: [message({ id: "first" }), message({ id: "second" })] },
  { responses: [message({ id: "other-run", runId: "other" })] },
])("preserves separate paused segments instead of guessing an answer identity", ({ responses }) => {
  store().addMessage(submitted());
  store().addMessage(message({ id: "local-answer", runId: "run", isTemporaryId: true }));
  store().rereadMessages([
    submitted({ id: "saved-question", isTemporaryId: false }),
    ...responses,
    submitted({ id: "later", clientMessageId: "later", isTemporaryId: false }),
  ]);
  expect(store().messages.some((item) => item.id === "local-answer")).toBe(true);
});

it("reconciles the question before any answer arrived, including normalized stored text", () => {
  store().addMessage(submitted({ content: " repeat " }));
  store().rereadMessages([
    submitted({ id: "saved-question", content: "repeat", isTemporaryId: false }),
  ]);
  expect(store().messages.map((item) => item.id)).toEqual(["saved-question"]);
  expect(store().messages[0]?.content).toBe("repeat");
});

it("does not guess when a client reused a correlation id for distinct persisted prompts", () => {
  store().addMessage(submitted());
  store().rereadMessages([
    submitted({ id: "one", isTemporaryId: false }),
    submitted({ id: "two", isTemporaryId: false }),
  ]);
  expect(store().messages.map((item) => item.id)).toEqual(["one", "two", "local-question"]);
});

it("uses the run identity when another participant's prompt interleaves the saved answer", () => {
  store().addMessage(submitted());
  store().addMessage(message({ id: "partial", runId: "ours", isTemporaryId: true }));
  store().rereadMessages([
    submitted({ id: "saved-question", isTemporaryId: false }),
    submitted({ id: "other-question", clientMessageId: "other", isTemporaryId: false }),
    message({ id: "saved-answer", runId: "ours", content: "Finished" }),
  ]);
  expect(store().messages.map((item) => item.id)).toEqual([
    "saved-question",
    "other-question",
    "saved-answer",
  ]);
});

it("retains late next-step buttons when an older history request finishes", () => {
  const saved = message({
    id: "answer",
    conversationId: "c",
    content: "Answer",
    toolCalls: [
      {
        id: "next_steps_answer",
        name: "suggest_next_steps",
        args: { steps: ["Make a table"] },
        result: JSON.stringify({ steps: ["Make a table"] }),
        status: "completed",
      },
    ],
  });
  store().addMessage(saved);
  store().rereadMessages([{ ...saved, toolCalls: [] }]);
  expect(store().messages.find((m) => m.id === "answer")?.toolCalls?.[0]?.args.steps).toEqual([
    "Make a table",
  ]);
});

describe("a saved message arriving before its acknowledgement", () => {
  it("keeps one answer and its tool results when the live id becomes the stored id", () => {
    const local = message({
      id: "live",
      isTemporaryId: true,
      renderKey: "stable",
      content: "One answer.",
      toolCalls: [toolCall({ name: "propose_setup" })],
    });
    store().addMessage(message({ id: "question", role: "user", content: "Hello" }));
    store().addMessage(local);
    store().rereadMessages([
      message({ id: "question", role: "user", content: "Hello" }),
      message({ id: "saved", content: "One answer." }),
    ]);
    store().updateMessage("live", (msg) => ({ ...msg, id: "saved", isTemporaryId: false }));
    expect(store().messages.map((msg) => msg.id)).toEqual(["question", "saved"]);
    expect(store().messages[1]).toMatchObject({
      renderKey: "stable",
      content: "One answer.",
      toolCalls: local.toolCalls,
    });
    store().rereadMessages([
      message({ id: "question", role: "user", content: "Hello" }),
      message({ id: "saved", content: "One answer.", toolCalls: local.toolCalls }),
    ]);
    expect(store().messages).toHaveLength(2);
  });

  it("does not merge distinct stored segments just because their text matches", () => {
    store().addMessage(message({ id: "first", content: "Same." }));
    store().addMessage(message({ id: "second", content: "Same." }));
    store().updateMessage("second", (msg) => ({ ...msg, isStreaming: false }));
    expect(store().messages.map((msg) => msg.id)).toEqual(["first", "second"]);
  });
});

it("ignores a late update for a turn removed during navigation", () => {
  const updater = vi.fn();
  store().updateMessage("no-longer-present", updater);
  expect(updater).not.toHaveBeenCalled();
});

describe("HTTP continuation reconciliation", () => {
  const call = toolCall({ id: "verified-tasks", status: "completed" });
  const local = () =>
    message({
      id: "resume-local",
      runId: "run",
      content: "Ten tasks created.",
      isLocalContinuation: true,
      toolCalls: [call],
    });
  const persisted = () => [
    message({ id: "saved-tools", runId: "run", toolCalls: [call] }),
    message({ id: "saved-final", runId: "run", content: "Ten tasks created." }),
  ];
  it("replaces the local answer when its persisted text and calls arrive in separate rows", () => {
    store().addMessage(local());
    store().rereadMessages(persisted());
    expect(store().messages.map((m) => m.id)).toEqual(["saved-tools", "saved-final"]);
    expect(store().messages.filter((m) => m.content === "Ten tasks created.")).toHaveLength(1);
    expect(store().messages[1]?.renderKey).toBe("resume-local");
  });
  it("does not add a second answer when the persisted update beats the HTTP response", () => {
    store().rereadMessages(persisted());
    store().addMessage(local());
    expect(store().messages).toHaveLength(2);
  });
  it("keeps an unpersisted segment or another run even when its answer has identical text", () => {
    store().addMessage(local());
    store().rereadMessages(persisted().map((m) => ({ ...m, runId: "another" })));
    expect(store().messages.some((m) => m.id === "resume-local")).toBe(true);
    store().rereadMessages(persisted().map((m) => ({ ...m, toolCalls: [] })));
    expect(store().messages.some((m) => m.id === "resume-local")).toBe(true);
  });
  it("reconciles a tool-only continuation without matching unrelated empty rows", () => {
    store().addMessage({ ...local(), content: "" });
    store().rereadMessages(persisted());
    expect(store().messages).toHaveLength(2);
    expect(store().messages[0]?.renderKey).toBe("resume-local");
  });
});

describe("room thread reconciliation", () => {
  const identity: TranscriptIdentity = {
    conversationId: "room",
    selectionVersion: 1,
    accountId: "me",
    tenantId: "org",
  };
  const reply = (id: string, root = "root-a", changes: Partial<ChatMessage> = {}) =>
    message({ id, conversationId: "room", threadRootMessageId: root, content: id, ...changes });

  it("merges only the authorized root while retaining an in-progress answer and other scopes", () => {
    store().rereadMessages([message({ id: "main", conversationId: "room" })], identity);
    store().addMessage(reply("live-a", "root-a", { isStreaming: true, content: "Half" }));
    store().addMessage(reply("reply-b", "root-b"));
    store().rereadRoomThread(
      [reply("saved-a"), reply("live-a", "root-a", { content: "Old snapshot" })],
      "root-a",
      identity,
    );
    store().appendTextDelta("live-a", " finished");
    expect(store().messages.map((row) => row.id)).toEqual(["main", "reply-b", "saved-a", "live-a"]);
    expect(store().messages.at(-1)?.content).toBe("Half finished");
    store().addMessage(message({ id: "main-new", conversationId: "room" }));
    store().rereadMessages(
      [
        message({ id: "main", conversationId: "room" }),
        message({ id: "main-new", conversationId: "room" }),
      ],
      identity,
    );
    expect(store().messages.find((row) => row.id === "saved-a")?.threadRootMessageId).toBe(
      "root-a",
    );
    expect(store().messages.find((row) => row.id === "reply-b")?.threadRootMessageId).toBe(
      "root-b",
    );
    store().appendTextDelta("live-a", " again");
    expect(store().messages.find((row) => row.id === "live-a")?.content).toBe(
      "Half finished again",
    );
  });

  it.each([
    null,
    { ...identity, conversationId: "other" },
    { ...identity, selectionVersion: 2 },
    { ...identity, accountId: "other" },
    { ...identity, tenantId: "other" },
  ])("rejects scoped history without the exact committed identity (%j)", (loaded) => {
    const before = [reply("held", "root-b")];
    useChatStore.setState({ messages: before, loadedTranscript: loaded });
    store().rereadRoomThread([reply("incoming")], "root-a", identity);
    expect(store().messages).toBe(before);
  });

  it.each([
    reply("foreign-room", "root-a", { conversationId: "elsewhere" }),
    reply("foreign-root", "root-b"),
  ])("rejects mixed-scope response rows (%j)", (foreign) => {
    store().rereadMessages([], identity);
    const before = store().messages;
    store().rereadRoomThread([reply("allowed"), foreign], "root-a", identity);
    expect(store().messages).toBe(before);
  });

  it("keeps empty history and drafts through a conversation close, then invalidates drafts on reset", () => {
    store().rereadMessages([], identity);
    store().addMessage(reply("live", "root-a", { isStreaming: true }));
    store().rereadRoomThread([], "root-a", identity);
    expect(store().messages[0]?.id).toBe("live");
    store().updateRoomDraft("scope", (draft) => ({ ...draft, content: "Keep me" }));
    store().updateRoomDraft("scope", (draft) => ({ ...draft, agentId: "writer" }));
    store().clearMessages();
    expect(store().roomDrafts.scope).toMatchObject({ content: "Keep me", agentId: "writer" });
    const generation = store().roomDraftGeneration;
    store().clearRoomDrafts();
    expect(store().roomDrafts).toEqual({});
    expect(store().roomDraftGeneration).toBe(generation + 1);
  });
});
