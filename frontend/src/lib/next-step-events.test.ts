import { describe, expect, it } from "vitest";
import { nextStepEvent, retainNextSteps, withNextSteps } from "./next-step-events";
import type { ChatMessage } from "@/types/chat";

const event = { conversation_id: "c", message_id: "m", steps: ["Make a table"] };
const message = (extra: Partial<ChatMessage> = {}): ChatMessage => ({
  id: "m",
  conversationId: "c",
  role: "assistant",
  content: "Answer",
  timestamp: new Date(),
  ...extra,
});

describe("late next-step events", () => {
  it.each([
    null,
    [],
    1,
    {},
    { ...event, conversation_id: 1 },
    { ...event, conversation_id: "" },
    { ...event, message_id: null },
    { ...event, message_id: "" },
    { ...event, steps: "bad" },
    { ...event, steps: ["a", "b", "c", "d"] },
    { ...event, steps: [" "] },
    { ...event, steps: [1] },
    { ...event, steps: ["a".repeat(81)] },
  ])("rejects malformed payload %j", (data) => {
    expect(nextStepEvent(data)).toBeNull();
  });
  it("accepts a helper completion with no suggestions", () => {
    expect(nextStepEvent({ ...event, steps: [] })).toEqual({ ...event, steps: [] });
    const original = message();
    expect(withNextSteps(original, { ...event, steps: [] })).toBe(original);
  });
  it("validates the targeted wire payload", () => {
    expect(nextStepEvent(event)).toEqual(event);
  });
  it.each([{ id: "other" }, { conversationId: "other" }, { role: "user" as const }])(
    "does not change another bubble %j",
    (extra) => {
      const old = message(extra);
      expect(withNextSteps(old, event)).toBe(old);
    },
  );
  it("appends buttons without touching the text, stream state or ordered parts", () => {
    const old = message({
      isStreaming: true,
      parts: [{ id: "text", type: "text", content: "Answer" }],
    });
    const updated = withNextSteps(old, event);
    expect(updated.content).toBe("Answer");
    expect(updated.isStreaming).toBe(true);
    expect(updated.parts?.[0]).toBe(old.parts?.[0]);
    expect(updated.parts?.[1]?.toolCall?.name).toBe("suggest_next_steps");
    expect(withNextSteps(updated, event)).toBe(updated);
  });
  it("keeps the flat transcript shape when no parts were recorded", () => {
    const updated = withNextSteps(message(), event);
    expect(updated.parts).toBeUndefined();
    expect(updated.toolCalls?.[0]?.args.steps).toEqual(event.steps);
  });
  it("retains persisted late buttons against an earlier history snapshot", () => {
    const local = withNextSteps(message(), event);
    const reloaded = retainNextSteps(message(), local);
    expect(reloaded.toolCalls).toEqual(local.toolCalls);
    expect(retainNextSteps(reloaded, local)).toBe(reloaded);
  });
  it("does not carry ordinary tools, unfinished calls or invalid steps into a stale read", () => {
    const old = withNextSteps(message(), event);
    const call = old.toolCalls![0]!;
    const incoming = message();
    for (const tool of [
      { ...call, name: "web_search" },
      { ...call, id: "ordinary" },
      { ...call, status: "running" as const },
      { ...call, args: { steps: [] } },
    ]) {
      expect(retainNextSteps(incoming, message({ toolCalls: [tool] }))).toBe(incoming);
    }
    expect(retainNextSteps(incoming, message())).toBe(incoming);
  });
});
