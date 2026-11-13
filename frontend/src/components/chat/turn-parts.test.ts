import { createElement } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MessagePart, ToolCall } from "@/types";

import { TurnParts, browseCalls, type PartRun } from "./turn-parts";

vi.mock("./tool-call-card", () => ({
  ToolCallCard: ({ toolCall }: { toolCall: ToolCall }) =>
    createElement("span", null, toolCall.name),
}));

vi.mock("@/components/phone/phone-call-card", () => ({
  PhoneCallCard: ({ callId }: { callId: string }) =>
    createElement("span", null, `Phone call ${callId}`),
}));

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

it("keeps narration in place when more work arrives during a live turn", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  const narration: MessagePart = {
    id: "narration",
    type: "text",
    content: "Checking the existing board.",
  };
  const before = foldWork(runsOf([tool("first", "search_tools"), narration]), false, true);
  const after = foldWork(
    runsOf([tool("first", "search_tools"), narration, tool("second", "read_file")]),
    false,
    true,
  );
  expect(before?.folded.map((run) => (run.kind === "other" ? run.part.id : "tools"))).toEqual([
    "tools",
    "narration",
  ]);
  expect(after?.folded.map((run) => (run.kind === "other" ? run.part.id : "tools"))).toEqual([
    "tools",
    "narration",
    "tools",
  ]);
  expect(after?.shown).toEqual([]);
  expect(after?.steps).toBe(2);
});

it("leaves a final answer without prior work directly visible", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  expect(
    foldWork(runsOf([{ id: "answer", type: "text", content: "Hello." }]), false, false),
  ).toBeNull();
});

it("keeps a report delivered before a question visible after the run resumes", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  const report: MessagePart = { id: "report", type: "text", content: "Audit findings." };
  const conclusion: MessagePart = { id: "conclusion", type: "text", content: "No changes made." };
  const split = foldWork(
    runsOf([
      tool("inspect", "read_file"),
      report,
      tool("question", "ask_user_question"),
      tool("follow-up", "read_file"),
      conclusion,
    ]),
  );
  expect(split?.shown.flatMap((run) => (run.kind === "other" ? [run.part.id] : []))).toEqual([
    "report",
    "conclusion",
  ]);
  expect(split?.steps).toBe(3);
  expect(split?.folded.every((run) => run.kind === "tools")).toBe(true);
});

it("recognizes renamed questions without trusting an external tool with the same name", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  const report: MessagePart = { id: "report", type: "text", content: "Audit findings." };
  const question = tool("question", "clarify");
  question.toolCall = { ...question.toolCall!, tool_id: "ask_user_question" };
  expect(foldWork(runsOf([report, question]))?.shown).toHaveLength(1);
  const external = tool("external", "ask_user_question");
  external.toolCall = { ...external.toolCall!, presentation_kind: "generic" };
  expect(foldWork(runsOf([report, external]))?.shown).toEqual([]);
});

it("retains an already delivered report when later work is stopped", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  const split = foldWork(
    runsOf([
      tool("inspect", "read_file"),
      { id: "report", type: "text", content: "Completed audit." },
      tool("question", "ask_user_question"),
      tool("later", "read_file"),
    ]),
    true,
  );
  expect(split?.shown.map((run) => run.kind === "other" && run.part.id)).toEqual(["report"]);
});

it("keeps text before a stored question visible and leaves reasoning folded", async () => {
  const { foldWork, runsOf } = await import("./turn-parts");
  const split = foldWork(
    runsOf([
      { id: "thinking", type: "thinking", content: "Private reasoning." },
      { id: "report", type: "text", content: "Audit findings." },
      { id: "question", type: "ask_user", question: "Apply changes?", answer: "Later" },
    ]),
  );
  expect(split?.shown.map((run) => run.kind === "other" && run.part.id)).toEqual(["report"]);
  expect(split?.folded.map((run) => run.kind === "other" && run.part.type)).toEqual([
    "thinking",
    "ask_user",
  ]);
});

it("keeps a telephone receipt visible as a result of the turn", () => {
  render(
    createElement(TurnParts, {
      parts: [{ id: "receipt", type: "phone_call", phoneCallId: "call-1" }],
      isStreaming: false,
      isUser: false,
      mcpServers: [],
    }),
  );
  expect(screen.getByText("Phone call call-1")).toBeVisible();
});

it("does not treat incomplete or nonvisual tool steps as visual artifacts", async () => {
  const { visualCalls } = await import("./turn-parts");
  const runs: PartRun[] = [
    {
      kind: "tools",
      isLast: false,
      parts: [{ id: "pending", type: "tool" }, tool("read", "read_file")],
    },
    { kind: "other", isLast: true, part: { id: "text", type: "text" }, content: "Done" },
  ];
  expect(visualCalls(runs)).toEqual([]);
});

it("groups tool calls between progress messages in the live turn", () => {
  render(
    createElement(TurnParts, {
      parts: [tool("read", "read_file"), tool("search", "search_tools")],
      isStreaming: true,
      isUser: false,
      mcpServers: [],
      openLastStep: true,
    }),
  );
  expect(screen.getByText("read_file")).toBeInTheDocument();
  expect(screen.getByText("search_tools")).toBeInTheDocument();
});

it("keeps renamed browser calls in the browse summary and excludes external collisions", () => {
  const alias = tool("renamed", "open_page");
  alias.toolCall = { ...alias.toolCall!, tool_id: "browser_open" };
  const external = tool("external", "browser_open");
  external.toolCall = { ...external.toolCall!, presentation_kind: "generic" };
  expect(
    browseCalls([{ kind: "tools", parts: [alias, external], isLast: true }]).map((call) => call.id),
  ).toEqual(["renamed"]);
});
