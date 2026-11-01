import { describe, expect, it } from "vitest";

import type { MessagePart, ToolCall } from "@/types";

import { browseCalls, type PartRun } from "./turn-parts";

function tool(id: string, name: string): MessagePart {
  const toolCall: ToolCall = { id, name, args: {}, status: "completed" };
  return { id, type: "tool", toolCall } as MessagePart;
}

describe("which calls contribute to a browse summary", () => {
  it("retains browser actions so their latest page can update the existing card", () => {
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

    expect(browseCalls(runs).map((call) => call.id)).toEqual(["a", "b", "c"]);
  });

  it("draws a second browser_open in the window the first one opened", () => {
    // Two opens in one turn drive the same tab - one window, not a window and
    // a "Browsed the web" line beside it.
    const runs: PartRun[] = [
      {
        kind: "tools",
        parts: [
          tool("google", "browser_open"),
          tool("scroll", "browser_scroll"),
          tool("bing", "browser_open"),
        ],
        isLast: true,
      },
    ];

    expect(browseCalls(runs).map((call) => call.id)).toEqual(["google", "scroll", "bing"]);
  });

  it("offers every desktop call, since a resumed run opens a window of its own", () => {
    const runs: PartRun[] = [
      {
        kind: "tools",
        parts: [
          tool("look", "computer_screenshot"),
          tool("act", "computer_act"),
          tool("open", "browser_open"),
          tool("again", "computer_screenshot"),
        ],
        isLast: true,
      },
    ];

    expect(browseCalls(runs).map((call) => call.id)).toEqual(["look", "act", "open", "again"]);
  });
});
