import { describe, expect, it } from "vitest";

import {
  replayStoredParts,
  buildAssistantParts,
  type RawMessagePart,
} from "./conversation-to-chat";
import { useChatStore } from "@/stores/chat-store";
import type { MessagePart, ToolCall } from "@/types";

/**
 * The same turn, watched live and reloaded, must be the same document.
 *
 * These are two independent producers of `message.parts` - the WebSocket handler
 * appending to the store as frames arrive, and `replayStoredParts` reading the row
 * back - and nothing but a test makes them agree. They did not: a turn that wrote
 * an introduction, drew three charts and then summarised them was four bubbles
 * live, and after a reload was one bubble whose introduction had never been saved
 * and whose charts had been reordered above it.
 *
 * The turn below is that turn. It is asserted as a *shape* rather than by id,
 * because the two sides key their parts differently on purpose: live keys a tool
 * part by the call id the backend sent, and a replayed one has to key its text
 * blocks off the row so React does not reuse a row across turns.
 */
const TOOL_CALLS: ToolCall[] = [
  { id: "call-1", name: "create_chart", args: {}, status: "completed", result: "{}" },
  { id: "call-2", name: "create_chart", args: {}, status: "completed", result: "{}" },
  { id: "call-3", name: "create_chart", args: {}, status: "completed", result: "{}" },
];

/** What the backend stores for that turn - `TurnTimeline.stored()`. */
const STORED: RawMessagePart[] = [
  { type: "thinking", text: "Deciding what to plot." },
  { type: "text", text: "Below are a few example charts." },
  { type: "tool", tool_call_id: "call-1" },
  { type: "tool", tool_call_id: "call-2" },
  { type: "tool", tool_call_id: "call-3" },
  { type: "text", text: "Done - three charts." },
];

/** Only what both sides claim to agree on: the sequence, and the words in it. */
function shapeOf(parts: MessagePart[]): Array<[string, string]> {
  return parts.map((part) => [
    part.type,
    part.type === "tool" ? (part.toolCall?.id ?? "") : (part.content ?? ""),
  ]);
}

/** Replay the frames the socket sent for that turn, through the real store. */
function liveParts(): MessagePart[] {
  const store = useChatStore.getState();
  store.clearMessages();
  store.addMessage({
    id: "temp-1",
    role: "assistant",
    content: "",
    timestamp: new Date(0),
    isStreaming: true,
    parts: [],
  });
  const { appendThinkingDelta, appendTextDelta, addToolCallPart } = useChatStore.getState();
  appendThinkingDelta("temp-1", "Deciding what to plot.");
  // Split, because a sentence arrives as several deltas and the space where two
  // meet is the thing a naive accumulator eats.
  appendTextDelta("temp-1", "Below are a few ");
  appendTextDelta("temp-1", "example charts.");
  for (const call of TOOL_CALLS) addToolCallPart("temp-1", call);
  appendTextDelta("temp-1", "Done - three charts.");
  return useChatStore.getState().messages[0]!.parts ?? [];
}

describe("a turn watched live and the same turn reloaded", () => {
  it("are the same sequence of the same words", () => {
    expect(shapeOf(replayStoredParts(STORED, TOOL_CALLS, "m-1"))).toEqual(shapeOf(liveParts()));
  });

  it("keeps both blocks of text, with the tools between them", () => {
    // The specific loss this replaced: one `content` column has room for one
    // block, so the introduction was dropped and the summary moved above the
    // charts it was written about.
    expect(shapeOf(replayStoredParts(STORED, TOOL_CALLS, "m-1"))).toEqual([
      ["thinking", "Deciding what to plot."],
      ["text", "Below are a few example charts."],
      ["tool", "call-1"],
      ["tool", "call-2"],
      ["tool", "call-3"],
      ["text", "Done - three charts."],
    ]);
  });

  it("gives every part its own React key, including two text blocks", () => {
    const ids = replayStoredParts(STORED, TOOL_CALLS, "m-1").map((part) => part.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("replaying a stored timeline", () => {
  it("drops an entry naming a tool call that is not there", () => {
    // The two are written in one transaction, so this means the call was deleted
    // from under the timeline - and half a step is worse than a missing one.
    const parts = replayStoredParts([{ type: "tool", tool_call_id: "gone" }], [], "m-1");

    expect(parts).toEqual([]);
  });

  it("drops an empty block rather than rendering an empty row", () => {
    const parts = replayStoredParts([{ type: "text", text: "" }], [], "m-1");

    expect(parts).toEqual([]);
  });

  it("drops a tool entry that names nothing at all", () => {
    const parts = replayStoredParts([{ type: "tool" }], TOOL_CALLS, "m-1");

    expect(parts).toEqual([]);
  });
});

describe("a turn stored before the order was recorded", () => {
  it("still reconstructs a readable timeline", () => {
    // The fallback, and the reason it cannot be deleted: these rows exist and
    // their order was never written down. It is a guess - reasoning, tools, then
    // the answer - and it is the best one available from flat fields.
    const parts = buildAssistantParts(TOOL_CALLS.slice(0, 1), "Thirty days.", "m-1", "Checking.");

    expect(shapeOf(parts)).toEqual([
      ["thinking", "Checking."],
      ["tool", "call-1"],
      ["text", "Thirty days."],
    ]);
  });
});
