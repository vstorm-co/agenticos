import { createElement } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MessagePart, ToolCall } from "@/types";

import { QuestionInteractionContext, type QuestionInteraction } from "./question-interaction";
import { MainChatContext } from "./main-chat-context";
import { TurnParts, browseCalls, chartCalls, type PartRun } from "./turn-parts";

vi.mock("./chart-message", () => ({
  parseChartResult: (value: unknown) =>
    typeof value === "string" && value === "chart-result" ? { title: "Quarterly revenue" } : null,
  ChartMessage: ({ spec }: { spec: { title: string } }) =>
    createElement("figure", null, spec.title),
}));

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

it("filters a finished turn's work while keeping its final answer visible", async () => {
  render(
    createElement(TurnParts, {
      parts: [
        tool("read", "read_file"),
        tool("write", "write_file"),
        { id: "answer", type: "text", content: "Your report is ready." },
      ],
      isStreaming: false,
      isUser: false,
      mcpServers: [],
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: /Worked/ }));
  await userEvent.click(screen.getByRole("button", { name: "Search and filter activity" }));
  await userEvent.type(screen.getByRole("searchbox"), "read_file");
  expect(screen.getByText("read_file", { exact: true })).toBeVisible();
  expect(screen.queryByText("write_file", { exact: true })).toBeNull();
  expect(screen.getByText("Your report is ready.")).toBeVisible();
});

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

it("uses the same work and prose boundaries before and after another tool arrives", async () => {
  const { groupWorkParts, runsOf } = await import("@/lib/turn-timeline");
  const narration: MessagePart = { id: "n", type: "text", content: "Checking the board." };
  expect(
    groupWorkParts(runsOf([tool("first", "search_tools"), narration])).map((group) => group.kind),
  ).toEqual(["work", "visible"]);
  expect(
    groupWorkParts(
      runsOf([tool("first", "search_tools"), narration, tool("second", "read_file")]),
    ).map((group) => group.kind),
  ).toEqual(["work", "visible", "work"]);
});

it("recognizes renamed question tools without trusting an external tool with that name", async () => {
  const { isQuestionRun, runsOf } = await import("@/lib/turn-timeline");
  const question = tool("question", "clarify");
  question.toolCall = { ...question.toolCall!, tool_id: "ask_user_question" };
  expect(isQuestionRun(runsOf([question])[0]!)).toBe(true);
  const external = tool("external", "ask_user_question");
  external.toolCall = { ...external.toolCall!, presentation_kind: "generic" };
  expect(isQuestionRun(runsOf([external])[0]!)).toBe(false);
});

it("keeps a stored question and its preceding report outside reasoning", async () => {
  const { groupWorkParts, runsOf } = await import("@/lib/turn-timeline");
  const groups = groupWorkParts(
    runsOf([
      { id: "thinking", type: "thinking", content: "Private reasoning." },
      { id: "report", type: "text", content: "Audit findings." },
      { id: "question", type: "ask_user", question: "Apply changes?", answer: "Later" },
    ]),
  );
  expect(groups.map((group) => group.kind)).toEqual(["work", "visible", "visible"]);
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
    }),
  );
  expect(screen.queryByText("read_file")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Working/ }));
  expect(screen.getByText("read_file")).toBeVisible();
  expect(screen.getByText("search_tools")).toBeVisible();
});

it("keeps consecutive live tool and reasoning steps in one activity group", () => {
  render(
    createElement(
      MainChatContext.Provider,
      { value: true },
      createElement(TurnParts, {
        parts: [
          tool("read", "read_file"),
          { id: "thinking", type: "thinking", content: "Checking another source." },
          tool("search", "search_tools"),
        ],
        isStreaming: true,
        isUser: false,
        mcpServers: [],
      }),
    ),
  );
  expect(screen.queryByRole("region")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Working/ }));
  const activity = within(screen.getByRole("region"));
  expect(activity.getByText("read_file")).toBeInTheDocument();
  expect(activity.getByText("search_tools")).toBeInTheDocument();
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

it("preserves the expanded timeline DOM while parking, resuming and completing a tool", () => {
  const part = tool("report", "create_routine");
  const draw = (status: ToolCall["status"], streaming: boolean) =>
    createElement(TurnParts, {
      parts: [{ ...part, toolCall: { ...part.toolCall!, status } }],
      isStreaming: streaming,
      isUser: false,
      mcpServers: [],
    });
  const { rerender } = render(draw("running", true));
  fireEvent.click(screen.getByRole("button", { name: /Working/ }));
  const step = screen.getByText("create_routine");
  const region = screen.getByRole("region");
  rerender(draw("awaiting_approval", false));
  expect(screen.getByText("create_routine")).toBe(step);
  expect(screen.getByRole("region")).toBe(region);
  rerender(draw("running", true));
  expect(screen.getByText("create_routine")).toBe(step);
  rerender(draw("completed", false));
  expect(screen.getByText("create_routine")).toBe(step);
  expect(screen.getByRole("region")).toBe(region);
  expect(step).toBeVisible();
});

it("keeps finished charts visible outside the collapsed work timeline", () => {
  const chart = tool("chart", "create_chart");
  chart.toolCall = { ...chart.toolCall!, result: "chart-result" };
  render(
    createElement(TurnParts, {
      parts: [chart, { id: "answer", type: "text", content: "The revenue increased." }],
      isStreaming: false,
      isUser: false,
      mcpServers: [],
    }),
  );
  expect(screen.getByRole("figure")).toHaveTextContent("Quarterly revenue");
  expect(screen.getByText("The revenue increased.")).toBeVisible();
  expect(screen.queryByRole("region")).toBeNull();
});

it("uses stable chart identity and excludes pending, failed and external calls", () => {
  const renamed = tool("renamed-chart", "revenue_plot");
  renamed.toolCall = { ...renamed.toolCall!, tool_id: "create_chart" };
  const external = tool("external", "create_chart");
  external.toolCall = { ...external.toolCall!, presentation_kind: "generic" };
  const pending = tool("pending", "create_chart");
  pending.toolCall = { ...pending.toolCall!, status: "running" };
  expect(
    chartCalls([
      {
        kind: "tools",
        parts: [renamed, external, pending, { id: "empty", type: "tool" }],
        isLast: true,
      },
    ]).map((c) => c.id),
  ).toEqual(["renamed-chart"]);
});

function pendingQuestion(toolCallIds: string[]): QuestionInteraction {
  return {
    id: "interaction",
    messageId: "answer",
    toolCallIds,
    questions: [
      {
        header: "Format",
        question: "Which format?",
        options: [{ label: "List" }],
        allowCustom: true,
      },
    ],
    submitting: false,
    disabled: false,
    onAnswer: vi.fn(),
  };
}

function interactiveTurn(
  parts: MessagePart[],
  interaction: QuestionInteraction,
  messageId = "answer",
) {
  return createElement(
    QuestionInteractionContext.Provider,
    { value: interaction },
    createElement(TurnParts, {
      parts,
      messageId,
      isStreaming: false,
      isUser: false,
      mcpServers: [],
    }),
  );
}

it("attaches a pending question interaction to its matching recorded invocation exactly once", () => {
  const question = tool("question", "ask_user_question");
  question.toolCall = {
    ...question.toolCall!,
    status: "awaiting_answer",
    args: {
      questions: [{ header: "Format", question: "Which format?", options: [{ label: "List" }] }],
    },
  };
  const interaction = pendingQuestion(["earlier", "question"]);
  const view = render(interactiveTurn([question], interaction));
  expect(view.container.querySelectorAll("[data-chat-question]")).toHaveLength(1);
  expect(screen.getByText("Which format?")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /1\s*List/ }));
  expect(interaction.onAnswer).toHaveBeenCalledOnce();
});

it("keeps a pending question visible before its invocation has arrived in the transcript", () => {
  const view = render(interactiveTurn([tool("read", "read_file")], pendingQuestion(["question"])));
  expect(view.container.querySelectorAll("[data-question-pending]")).toHaveLength(1);
  expect(screen.getByText("Which format?")).toBeVisible();
  expect(screen.queryByText("read_file")).toBeNull();
});

it("does not attach another message's pending question to this turn", () => {
  const view = render(
    interactiveTurn([tool("read", "read_file")], pendingQuestion(["question"]), "older"),
  );
  expect(view.container.querySelector("[data-chat-question]")).toBeNull();
});

it("keeps unmatched historical question diagnostics separate from the current pending question", () => {
  const previous = tool("previous", "ask_user_question");
  previous.toolCall = {
    ...previous.toolCall!,
    args: {
      questions: [{ header: "Earlier", question: "Continue?", options: [{ label: "Yes" }] }],
    },
    result: '{"Earlier":["Yes"]}',
  };
  const view = render(interactiveTurn([previous], pendingQuestion(["question"])));
  expect(view.container.querySelectorAll("[data-chat-question]")).toHaveLength(2);
  expect(view.container.querySelectorAll("[data-question-pending]")).toHaveLength(1);
  expect(screen.getByText("Which format?")).toBeVisible();
});

it("shows no stale work or question UI for an empty turn", () => {
  const view = render(
    createElement(TurnParts, { parts: [], isStreaming: true, isUser: false, mcpServers: [] }),
  );
  expect(view.container).toBeEmptyDOMElement();
});

it("does not turn an invalid chart result into a blank output card", () => {
  const chart = tool("invalid-chart", "create_chart");
  chart.toolCall = { ...chart.toolCall!, result: "invalid-chart-result" };
  render(
    createElement(TurnParts, { parts: [chart], isStreaming: false, isUser: false, mcpServers: [] }),
  );
  expect(screen.queryByRole("figure")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Worked/ }));
  expect(screen.getByText("create_chart")).toBeVisible();
});

it.each(["answer", "approval"] as const)(
  "keeps a delegated %s wait in the activity summary",
  (waitingFor) => {
    const part = tool("delegate", "task");
    render(
      createElement(TurnParts, {
        parts: [part],
        isStreaming: false,
        isUser: false,
        mcpServers: [],
        waitingFor,
      }),
    );
    expect(screen.queryByText("task")).toBeNull();
    const toggle = screen.getByRole("button", { expanded: false });
    expect(toggle).toHaveTextContent(
      waitingFor === "answer" ? "Waiting for an answer" : "Waiting for approval",
    );
  },
);
