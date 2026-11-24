import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { MessagePart, ToolCall } from "@/types";
import type { PartRun } from "./turn-parts";
import { filterTrace, TurnTrace } from "./turn-trace";

const tool = (id: string, status: ToolCall["status"] = "completed"): MessagePart => ({
  id,
  type: "tool",
  toolCall: { id, name: id, args: {}, status },
});
const other = (part: MessagePart): PartRun => ({
  kind: "other",
  part,
  content: part.content ?? "",
  isLast: false,
});
const tools = (...parts: MessagePart[]): PartRun => ({
  kind: "tools",
  parts: parts as [MessagePart, ...MessagePart[]],
  isLast: false,
});
const ids = (runs: PartRun[]) =>
  runs.flatMap((run) => (run.kind === "tools" ? run.parts.map((part) => part.id) : [run.part.id]));
const draw = (run: PartRun) => (
  <p key={run.kind === "tools" ? run.parts[0].id : run.part.id}>
    {run.kind === "tools" ? run.parts.map((part) => part.id).join(", ") : run.part.id}
  </p>
);

it("filters tools, thoughts, errors and messages without changing their chronology", () => {
  const runs = [
    other({ id: "thought", type: "thinking", content: "Compare options" }),
    tools(tool("read"), tool("failed", "error")),
    other({ id: "progress", type: "text", content: "Checking" }),
    other({ id: "guidance", type: "steer", content: "Use the latest report" }),
    other({ id: "answer", type: "ask_user", question: "Which one?", answer: "First" }),
    other({
      id: "workflow",
      type: "workflow_run",
      workflowRun: {
        workflowId: "w",
        workflowName: "Import",
        runId: "r",
        status: "failed",
        error: "Missing input",
      },
    }),
  ];
  const snapshot = JSON.stringify(runs);
  expect(ids(filterTrace(runs, "", "tools").runs)).toEqual(["read", "failed"]);
  expect(ids(filterTrace(runs, "", "thinking").runs)).toEqual(["thought"]);
  expect(ids(filterTrace(runs, "", "errors").runs)).toEqual(["failed", "workflow"]);
  expect(ids(filterTrace(runs, "", "messages").runs)).toEqual([
    "progress",
    "guidance",
    "answer",
    "workflow",
  ]);
  expect(ids(filterTrace(runs, "", "all").runs)).toEqual(ids(runs));
  expect(JSON.stringify(runs)).toBe(snapshot);
});

it("finds literal text in tool arguments and results, including punctuation", () => {
  const call = tool("read");
  call.toolCall!.args = { path: "Reports/a+b[1].md" };
  call.toolCall!.result = { rows: [{ note: "North Region" }] };
  const runs = [tools(call, tool("unrelated"))];
  expect(ids(filterTrace(runs, " A+B[1] ", "all").runs)).toEqual(["read"]);
  expect(ids(filterTrace(runs, "NORTH REGION", "tools").runs)).toEqual(["read"]);
  expect(filterTrace(runs, ".*", "all").shown).toBe(0);
});

it("keeps unanswered, approval and setup steps visible when a filter excludes them", () => {
  const runs = [
    tools(tool("approval", "awaiting_approval"), tool("tool-question", "awaiting_answer")),
    other({ id: "question", type: "ask_user", question: "Confirm?" }),
    other({ id: "blank-answer", type: "ask_user", question: "Pick?", answer: " " }),
    other({ id: "setup", type: "model_setup", setupAgentId: "agent" }),
    other({ id: "done-question", type: "ask_user", question: "Confirm?", answer: "Yes" }),
    tools(tool("done")),
  ];
  const result = filterTrace(runs, "no match", "thinking");
  expect(ids(result.runs)).toEqual([
    "approval",
    "tool-question",
    "question",
    "blank-answer",
    "setup",
  ]);
  expect(result).toMatchObject({ total: 7, shown: 5, attention: 5 });
});

it("retains the original streaming flags instead of making the last search hit look live", () => {
  const earlier = tools(tool("match"), tool("skip"));
  const live = {
    ...other({ id: "live", type: "thinking", content: "Still working" }),
    isLast: true,
  };
  const result = filterTrace([earlier, live], "match", "all");
  expect(result.runs).toHaveLength(1);
  expect(result.runs[0]!.isLast).toBe(false);
  expect(ids(earlier.kind === "tools" ? [earlier] : [])).toEqual(["match", "skip"]);
  expect(filterTrace([], "", "all")).toMatchObject({ runs: [], shown: 0, total: 0 });
});

it("offers an opt-in search, combines it with type filters, and clearly reports no results", async () => {
  render(<TurnTrace runs={[tools(tool("read"), tool("failed", "error"))]} render={draw} />);
  expect(screen.queryByRole("searchbox")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Search and filter activity" }));
  expect(screen.getByRole("search", { name: "Search this turn's activity" })).toBeVisible();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Show" }), "errors");
  expect(screen.getByText("failed", { exact: true })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("1 of 2 entries");
  await userEvent.type(screen.getByRole("searchbox"), "missing");
  expect(screen.getByText("No activity matches these filters.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByText("read, failed")).toBeVisible();
  expect(screen.getByRole("combobox")).toHaveValue("all");
});

it("clears active filters with Escape and when closing their controls", async () => {
  render(<TurnTrace runs={[tools(tool("read"))]} render={draw} />);
  const toggle = screen.getByRole("button", { name: "Search and filter activity" });
  await userEvent.click(toggle);
  const search = screen.getByRole("searchbox");
  fireEvent.keyDown(search, { key: "ArrowDown" });
  fireEvent.keyDown(search, { key: "Escape" });
  await userEvent.type(search, "missing");
  fireEvent.keyDown(search, { key: "Escape" });
  expect(search).toHaveValue("");
  expect(screen.getByText("read", { exact: true })).toBeVisible();
  await userEvent.selectOptions(screen.getByRole("combobox"), "thinking");
  await userEvent.click(toggle);
  expect(screen.queryByRole("searchbox")).toBeNull();
  expect(screen.getByText("read", { exact: true })).toBeVisible();
  await userEvent.click(toggle);
  expect(screen.getByRole("combobox")).toHaveValue("all");
});

it("keeps the selected filter as streaming work arrives and explains attention exceptions", async () => {
  const first = [tools(tool("read"))];
  const view = render(<TurnTrace runs={first} render={draw} />);
  await userEvent.click(screen.getByRole("button", { name: "Search and filter activity" }));
  await userEvent.type(screen.getByRole("searchbox"), "next");
  view.rerender(
    <TurnTrace
      runs={[...first, tools(tool("next"), tool("approval", "awaiting_approval"))]}
      render={draw}
    />,
  );
  expect(screen.getByRole("searchbox")).toHaveValue("next");
  expect(screen.getByText("next, approval")).toBeVisible();
  expect(screen.getByText("Steps waiting for you stay visible.")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("2 of 3 entries");
});
