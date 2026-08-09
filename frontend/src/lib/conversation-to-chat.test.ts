import { describe, expect, it } from "vitest";

import {
  buildAssistantParts,
  conversationMessageToChatMessage,
  conversationMessagesToChatMessages,
  type RawMessage,
} from "./conversation-to-chat";
import type { ToolCall } from "@/types";

function raw(overrides: Partial<RawMessage> = {}): RawMessage {
  return {
    id: "m-1",
    conversation_id: "c-1",
    role: "assistant",
    content: "Refunds run to thirty days.",
    created_at: "2026-07-31T12:00:00Z",
    ...overrides,
  };
}

function toolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: "tc-1", name: "search_documents", args: {}, status: "completed", ...overrides };
}

/**
 * Replaying a saved conversation as the live chat renders it.
 *
 * The database stores a flat row - content, plus tool calls, plus thinking - with
 * nothing saying what happened when. The live stream has an ordered timeline, so
 * this rebuilds one: reasoning, then the tools that ran, then the answer they
 * produced. Getting the order wrong puts the answer above the work that led to
 * it, and a reloaded conversation stops matching the one somebody just watched.
 */
describe("buildAssistantParts", () => {
  it("puts the reasoning first, then the tools, then the answer", () => {
    const parts = buildAssistantParts([toolCall()], "Thirty days.", "m-1", "Checking the policy.");

    expect(parts.map((part) => part.type)).toEqual(["thinking", "tool", "text"]);
  });

  it("keys each part off the message, so React does not reuse a row across turns", () => {
    const parts = buildAssistantParts([toolCall()], "Thirty days.", "m-1", "Thinking.");

    expect(parts.map((part) => part.id)).toEqual(["m-1-thinking", "tc-1", "m-1-text"]);
  });

  it("omits the reasoning when the model published none", () => {
    // Which is every turn on a model with thinking switched off.
    expect(buildAssistantParts([], "Thirty days.", "m-1").map((part) => part.type)).toEqual([
      "text",
    ]);
    expect(buildAssistantParts([], "Thirty days.", "m-1", null).map((part) => part.type)).toEqual([
      "text",
    ]);
  });

  it("omits the answer when a turn produced none", () => {
    // A run stopped at an approval has its tool call and nothing after it; a
    // blank text bubble would read as an empty reply.
    const parts = buildAssistantParts([toolCall({ status: "pending" })], "", "m-1");

    expect(parts.map((part) => part.type)).toEqual(["tool"]);
  });
});

describe("conversationMessageToChatMessage", () => {
  it("carries the fields the chat renders a turn from", () => {
    const message = conversationMessageToChatMessage(
      raw({ agent_id: "a-1", agent_version: 3, thinking: "Checking." }),
    );

    expect(message).toMatchObject({
      id: "m-1",
      role: "assistant",
      content: "Refunds run to thirty days.",
      conversationId: "c-1",
      agentId: "a-1",
      agentVersion: 3,
      thinking: "Checking.",
    });
    expect(message.timestamp).toEqual(new Date("2026-07-31T12:00:00Z"));
  });

  it("renames a failed tool call to the status the UI knows", () => {
    // The backend says `failed`; every renderer in the chat branches on `error`,
    // and an unrecognised status renders as still-running forever.
    const message = conversationMessageToChatMessage(
      raw({
        tool_calls: [
          { tool_call_id: "tc-1", tool_name: "search_documents", args: {}, status: "failed" },
        ],
      }),
    );

    expect(message.toolCalls?.[0]).toMatchObject({
      id: "tc-1",
      name: "search_documents",
      status: "error",
    });
  });

  it("leaves every other status alone", () => {
    const message = conversationMessageToChatMessage(
      raw({
        tool_calls: [
          { tool_call_id: "tc-1", tool_name: "x", args: {}, result: "42", status: "completed" },
        ],
      }),
    );

    expect(message.toolCalls?.[0]).toMatchObject({ status: "completed", result: "42" });
  });

  it("builds a timeline for an assistant turn and none for a person's", () => {
    // A user message has no tools and no reasoning; giving it parts would make
    // the renderer look for a timeline that says nothing.
    expect(conversationMessageToChatMessage(raw()).parts).toBeDefined();
    expect(conversationMessageToChatMessage(raw({ role: "user" })).parts).toBeUndefined();
  });

  it("keeps the attachments, and their ids, which is what a re-send needs", () => {
    const message = conversationMessageToChatMessage(
      raw({
        role: "user",
        files: [
          { id: "f-1", filename: "invoice.pdf", mime_type: "application/pdf", file_type: "pdf" },
        ],
      }),
    );

    expect(message.files).toHaveLength(1);
    expect(message.fileIds).toEqual(["f-1"]);
  });

  it("treats a non-list files field as no attachments rather than crashing on it", () => {
    // Reachable from an older row where the column held null.
    const message = conversationMessageToChatMessage(raw({ files: null }));

    expect(message.files).toBeUndefined();
    expect(message.fileIds).toBeUndefined();
  });

  it("carries a rating and the tally beside it", () => {
    const message = conversationMessageToChatMessage(
      raw({ user_rating: 1, rating_count: { likes: 3, dislikes: 1 } }),
    );

    expect(message).toMatchObject({ user_rating: 1, rating_count: { likes: 3, dislikes: 1 } });
  });

  it("leaves the optional fields absent rather than null", () => {
    // `undefined` is what the live shape uses; a null would render as a rating of
    // zero and an agent id of nothing.
    const message = conversationMessageToChatMessage(raw({ agent_id: null, user_rating: null }));

    expect(message.agentId).toBeUndefined();
    expect(message.user_rating).toBeUndefined();
    expect(message.toolCalls).toBeUndefined();
  });
});

describe("conversationMessagesToChatMessages", () => {
  it("converts a whole history in order", () => {
    const messages = conversationMessagesToChatMessages([
      raw({ id: "m-1", role: "user", content: "How long?" }),
      raw({ id: "m-2" }),
    ]);

    expect(messages.map((message) => message.id)).toEqual(["m-1", "m-2"]);
  });
});

describe("what a stored message says it cost", () => {
  it("travels with the message, so a reopened thread prices its own answers", () => {
    const message = conversationMessageToChatMessage({
      id: "m-1",
      conversation_id: "c-1",
      role: "assistant",
      content: "answered",
      created_at: "2026-08-03T20:00:00Z",
      input_tokens: 4055,
      output_tokens: 24,
      cost_usd: "0.001200",
    });

    expect(message.usage).toMatchObject({
      input_tokens: 4055,
      output_tokens: 24,
      cost_usd: 0.0012,
    });
  });

  it("carries nothing for a message written before it was recorded", () => {
    const message = conversationMessageToChatMessage({
      id: "m-1",
      conversation_id: "c-1",
      role: "assistant",
      content: "answered",
      created_at: "2026-08-03T20:00:00Z",
    });

    expect(message.usage).toBeUndefined();
  });

  it("keeps the agent and the version the row names", () => {
    // The chat page had its own copy of this mapping that dropped both, so a
    // reloaded transcript drew a generic robot beside every answer.
    const message = conversationMessageToChatMessage({
      id: "m-1",
      conversation_id: "c-1",
      role: "assistant",
      content: "answered",
      created_at: "2026-08-03T20:00:00Z",
      agent_id: "a-1",
      agent_version: 3,
    });

    expect(message).toMatchObject({ agentId: "a-1", agentVersion: 3 });
  });
});

describe("which run a replayed turn belongs to", () => {
  it("carries the run through, so a reloaded turn groups as the live one did", () => {
    // A run that parked on an approval leaves several messages. The list draws
    // them as one turn by matching this id, and a reload that dropped it would
    // show three agents where the live chat showed one.
    expect(conversationMessageToChatMessage(raw({ run_id: "r-9" })).runId).toBe("r-9");
  });

  it("leaves a turn written outside a run ungrouped", () => {
    // Null is "not recorded", not "the same run as the one above".
    expect(conversationMessageToChatMessage(raw({ run_id: null })).runId).toBeUndefined();
  });
});

describe("a stored tool call that never finished", () => {
  it("stops looking like it is running", () => {
    // Nothing on this screen can finish it: the frames that would have are long
    // gone, and some rows never get an outcome at all - an expired approval, a run
    // that broke mid-call. Left as `running` the step pulsed forever, in the
    // present tense, under a conversation that ended days ago.
    const message = conversationMessageToChatMessage(
      raw({
        tool_calls: [
          { tool_call_id: "tc-1", tool_name: "execute", args: {}, status: "running" },
          { tool_call_id: "tc-2", tool_name: "execute", args: {}, status: "pending" },
        ],
      }),
    );

    expect(message.toolCalls?.map((call) => call.status)).toEqual(["unfinished", "unfinished"]);
  });

  it("keeps every status that did record an outcome", () => {
    // `failed` is this repository's word for what the chat calls `error`.
    const message = conversationMessageToChatMessage(
      raw({
        tool_calls: [
          { tool_call_id: "tc-1", tool_name: "execute", args: {}, status: "completed" },
          { tool_call_id: "tc-2", tool_name: "execute", args: {}, status: "failed" },
        ],
      }),
    );

    expect(message.toolCalls?.map((call) => call.status)).toEqual(["completed", "error"]);
  });
});
