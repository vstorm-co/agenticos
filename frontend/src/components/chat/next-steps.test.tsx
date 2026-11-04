import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NextSteps, nextStepsOf } from "./next-steps";
import type { ChatMessage, ToolCall } from "@/types/chat";

/**
 * The latest answer's next steps, on the composer (#2301): offered only while
 * the conversation ends on that finished answer, and a click is the message.
 */

const offered: ToolCall = {
  id: "s-1",
  name: "suggest_next_steps",
  args: {},
  status: "completed",
  result: JSON.stringify({ steps: ["Make it a table", "Do this every Monday"] }),
};

function answer(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "Done",
    timestamp: new Date(),
    toolCalls: [offered],
    ...overrides,
  };
}

describe("nextStepsOf", () => {
  it("offers the steps of the answer the conversation ends on", () => {
    expect(nextStepsOf([answer()], false)).toEqual(["Make it a table", "Do this every Monday"]);
  });

  it("offers nothing while a turn runs, under a streaming answer, or after the person spoke", () => {
    expect(nextStepsOf([answer()], true)).toEqual([]);
    expect(nextStepsOf([answer({ isStreaming: true })], false)).toEqual([]);
    expect(
      nextStepsOf([answer(), answer({ id: "q", role: "user", content: "and?" })], false),
    ).toEqual([]);
    expect(nextStepsOf([], false)).toEqual([]);
  });
});

describe("NextSteps", () => {
  it("sends the step picked", async () => {
    const onPick = vi.fn();
    render(<NextSteps steps={["Make it a table"]} onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "Make it a table" }));

    expect(onPick).toHaveBeenCalledWith("Make it a table");
  });

  it("draws nothing without steps", () => {
    const { container } = render(<NextSteps steps={[]} onPick={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });
});
