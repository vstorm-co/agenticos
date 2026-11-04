import { describe, expect, it } from "vitest";
import { coalesceChatFrames } from "./chat-frame-batch";

const frame = (type: string, data: Record<string, unknown>) =>
  new MessageEvent("message", { data: JSON.stringify({ type, data }) });
const read = (events: MessageEvent[]) => events.map((event) => JSON.parse(event.data));

describe("chat frame coalescing", () => {
  it("joins a replay burst without changing its text", () => {
    const events = Array.from({ length: 200 }, (_, n) =>
      frame("text_delta", { index: 0, content: `${n} ` }),
    );
    expect(read(coalesceChatFrames(events))).toEqual([
      {
        type: "text_delta",
        data: { index: 0, content: Array.from({ length: 200 }, (_, n) => `${n} `).join("") },
      },
    ]);
  });

  it("retains control, tool, part-index and reasoning boundaries in order", () => {
    const events = [
      frame("model_request_start", {}),
      frame("thinking_delta", { index: 0, content: "think" }),
      frame("thinking_delta", { index: 0, content: " more" }),
      frame("text_delta", { index: 0, content: "a" }),
      frame("text_delta", { index: 1, content: "b" }),
      frame("tool_call", { tool_call_id: "t" }),
      frame("text_delta", { index: 1, content: "c" }),
      frame("text_delta", { index: 1, content: "d" }),
      frame("message_saved", { message_id: "m" }),
      frame("complete", {}),
      frame("session_ready", {}),
    ];
    const result = read(coalesceChatFrames(events));
    expect(result.map((event) => event.type)).toEqual([
      "model_request_start",
      "thinking_delta",
      "text_delta",
      "text_delta",
      "tool_call",
      "text_delta",
      "message_saved",
      "complete",
      "session_ready",
    ]);
    expect(result[1].data.content).toBe("think more");
    expect(result[5].data.content).toBe("cd");
  });

  it("preserves unexpected payloads for the existing handler instead of discarding them", () => {
    const events = [
      new MessageEvent("message", { data: null }),
      new MessageEvent("message", { data: "null" }),
      frame("text_delta", { content: 42 }),
      frame("text_delta", { content: "" }),
      new MessageEvent("message", { data: '{"type":"text_delta"}' }),
    ];
    expect(coalesceChatFrames(events)).toHaveLength(5);
    expect(coalesceChatFrames([])).toEqual([]);
    expect(() => coalesceChatFrames([new MessageEvent("message", { data: "bad JSON" })])).toThrow();
  });
});
