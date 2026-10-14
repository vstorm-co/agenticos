import { describe, expect, it } from "vitest";

import type { MessagePart, ToolCall } from "@/types";

import { browseCalls, type PartRun } from "./turn-parts";

function tool(id: string, name: string): MessagePart {
  const toolCall: ToolCall = { id, name, args: {}, status: "completed" };
  return { id, type: "tool", toolCall } as MessagePart;
}

describe("which calls open a browse panel", () => {
  it("is every browse_web and the browser_open that starts the agent driving", () => {
    const runs: PartRun[] = [
      {
        kind: "tools",
        parts: [tool("a", "browser_open"), tool("b", "browser_click"), tool("c", "browse_web")],
        isLast: false,
      },
      {
        kind: "other",
        part: { id: "t", type: "text" } as MessagePart,
        content: "ok",
        isLast: true,
      },
    ];

    expect(browseCalls(runs).map((call) => call.id)).toEqual(["a", "c"]);
  });
});
