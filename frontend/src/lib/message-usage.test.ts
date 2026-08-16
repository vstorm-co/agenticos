import { describe, expect, it } from "vitest";

import { latestUsage, storedUsage } from "./message-usage";
import type { ConversationMessage } from "@/types";

function message(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "m-1",
    conversation_id: "c-1",
    role: "assistant",
    content: "answered",
    created_at: "2026-08-03T20:00:00Z",
    ...overrides,
  };
}

/**
 * What a reopened conversation can say about what it cost.
 *
 * The numbers used to arrive only in the `complete` frame, so they existed for as
 * long as the tab did: reopening a thread showed no cost under the input and none
 * under any message, and they came back only after sending something new — which is
 * exactly when nobody is asking.
 */
describe("what a stored message says it cost", () => {
  it("carries the partial flag, so a reloaded turn draws the same caveat", () => {
    // The whole point of storing it: a live turn said the cost was a floor and a
    // reopened one said nothing, so the same answer read as exact the next day.
    const usage = storedUsage(
      message({ input_tokens: 10, output_tokens: 2, cost_usd: "0.0001", cost_is_partial: true }),
    );

    expect(usage?.cost_is_partial).toBe(true);
  });

  it("treats an unrecorded flag as an unmarked cost, not as a caveat", () => {
    // Null is every message written before the column existed. `true` is the only
    // claim this knows to be right, and the caveat is a claim too.
    const usage = storedUsage(message({ input_tokens: 10, output_tokens: 2, cost_usd: "0.0001" }));

    expect(usage?.cost_is_partial).toBe(false);
  });

  it("reads the split and the money off the row", () => {
    const usage = storedUsage(
      message({ input_tokens: 1200, output_tokens: 300, cost_usd: "0.012500" }),
    );

    expect(usage).toMatchObject({ input_tokens: 1200, output_tokens: 300, cost_usd: 0.0125 });
  });

  it("says nothing about a message nobody measured", () => {
    // Absent means "not recorded", never "free" - every message written before the
    // API recorded this carries nothing, and zeroes under an answer that cost money
    // is a worse lie than silence.
    expect(storedUsage(message())).toBeNull();
  });

  it("says nothing when only one half of the split is there", () => {
    expect(storedUsage(message({ input_tokens: 1200 }))).toBeNull();
    expect(storedUsage(message({ output_tokens: 300 }))).toBeNull();
  });

  it("reads a measured turn that genuinely cost nothing", () => {
    // A cached prompt on some providers really is free, and that is not the same
    // answer as "not recorded".
    const usage = storedUsage(message({ input_tokens: 10, output_tokens: 0, cost_usd: null }));

    expect(usage).toMatchObject({ input_tokens: 10, output_tokens: 0, cost_usd: 0 });
  });

  it("carries no budget or workspace figure", () => {
    // Those describe an organization *now*, not what a turn cost then - last month's
    // percentage-of-budget under an old message is a number that was never true.
    const usage = storedUsage(message({ input_tokens: 1, output_tokens: 1, cost_usd: "0.1" }));

    expect(usage).toMatchObject({
      budget_percent: null,
      agent_budget_percent: null,
      sandbox: null,
    });
  });
});

describe("the newest measured answer in a transcript", () => {
  it("is what the strip shows on a conversation nobody has sent to yet", () => {
    const usage = latestUsage(
      [
        message({ id: "m-1", input_tokens: 10, output_tokens: 10, cost_usd: "0.01" }),
        message({ id: "m-2", input_tokens: 900, output_tokens: 90, cost_usd: "0.09" }),
      ],
      "c-1",
    );

    expect(usage).toMatchObject({ input_tokens: 900 });
  });

  it("skips the trailing message when it is the person's own", () => {
    // A transcript often ends with a question nobody has answered yet.
    const usage = latestUsage(
      [
        message({ id: "m-1", input_tokens: 10, output_tokens: 10, cost_usd: "0.01" }),
        message({ id: "m-2", role: "user", content: "and again?" }),
      ],
      "c-1",
    );

    expect(usage).toMatchObject({ input_tokens: 10 });
  });

  it("skips an answer that was never measured", () => {
    const usage = latestUsage(
      [
        message({ id: "m-1", input_tokens: 10, output_tokens: 10, cost_usd: "0.01" }),
        message({ id: "m-2" }),
      ],
      "c-1",
    );

    expect(usage).toMatchObject({ input_tokens: 10 });
  });

  it("says nothing about a transcript with nothing measured in it", () => {
    expect(latestUsage([message({ role: "user", content: "hi" })], "c-1")).toBeNull();
    expect(latestUsage([], "c-1")).toBeNull();
  });

  it("says nothing while the transcript on hand belongs to the conversation just left", () => {
    // The store keeps the last transcript it loaded, so for the moment between the
    // click and the fetch landing, these messages are another thread's - and the strip
    // reported its tokens and its money under the new conversation.
    const measured = [
      message({ id: "m-1", input_tokens: 10, output_tokens: 10, cost_usd: "0.01" }),
    ];

    expect(latestUsage(measured, "c-2")).toBeNull();
    expect(latestUsage(measured, null)).toBeNull();
  });
});
