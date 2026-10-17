import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ToolCall } from "@/types";

import { TurnDelegations } from "./turn-delegations";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

const AGENTS = [
  { id: "a-fin", slug: "finance-analyst", name: "Finance Analyst", avatar_color: 8 },
  { id: "a-sup", slug: "support-desk", name: "Support Desk" },
];
// An agent the reader cannot open has no id, and still has a face from its handle.
const CHIEF = { id: null, slug: "chief-of-staff", name: "Chief of Staff" };

function asked(id: string, slug: string, status: ToolCall["status"] = "completed"): ToolCall {
  return {
    id,
    name: "task",
    args: { subagent_type: slug, description: `Brief for ${slug}` },
    result: `Answer from ${slug}`,
    status,
  };
}

/**
 * Who an answer was talked through with: one line under it, opening every
 * exchange at the side.
 */
describe("the team under an answer", () => {
  it("says nothing for a turn that asked nobody", () => {
    const { container } = render(
      <TurnDelegations
        toolCalls={[{ id: "x", name: "web_search", args: {}, status: "completed" }]}
        agents={AGENTS}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names each colleague once, and counts every exchange", () => {
    render(
      <TurnDelegations
        parent={CHIEF}
        toolCalls={[
          asked("1", "finance-analyst"),
          asked("2", "support-desk"),
          asked("3", "support-desk"),
        ]}
        agents={AGENTS}
      />,
    );

    expect(
      screen.getByText("Talked it through with Finance Analyst and Support Desk · 3 exchanges"),
    ).toBeInTheDocument();
  });

  it("opens the exchanges at the side, and moves between them", async () => {
    render(
      <TurnDelegations
        toolCalls={[asked("1", "finance-analyst"), asked("2", "support-desk", "error")]}
        agents={AGENTS}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Brief for finance-analyst")).toBeInTheDocument();
    expect(within(sheet).getByText("Answer from finance-analyst")).toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("tab", { name: "Support Desk" }));
    expect(within(sheet).getByText("failed")).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("reads every way a delegation can stand", async () => {
    render(
      <TurnDelegations
        toolCalls={[
          asked("1", "a-helper", "running"),
          asked("2", "b-helper", "awaiting_approval"),
          asked("3", "c-helper", "unfinished"),
        ]}
        agents={AGENTS}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));
    expect(screen.getByText("working…")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "B helper" }));
    expect(screen.getByText("waiting for approval")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "C helper" }));
    expect(screen.getByText("stopped")).toBeInTheDocument();
  });

  it("opens an exchange with no brief or answer to an empty record", async () => {
    render(
      <TurnDelegations
        toolCalls={[
          { id: "1", name: "task", args: { subagent_type: "support-desk" }, status: "running" },
        ]}
        agents={AGENTS}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));

    expect(screen.queryByText("Brief")).toBeNull();
    expect(screen.queryByText("Answer")).toBeNull();
  });

  it("reads a background delegation through the check of its task", async () => {
    const started: ToolCall = {
      id: "1",
      name: "task",
      args: { subagent_type: "support-desk" },
      status: "completed",
      result: "Task started in background.\nTask ID: t1\nSubagent: support-desk\n",
    };
    const { rerender } = render(<TurnDelegations toolCalls={[started]} agents={AGENTS} />);

    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));
    expect(screen.getByText("working…")).toBeInTheDocument();
    expect(screen.queryByText(/Task started in background/)).toBeNull();

    rerender(
      <TurnDelegations
        toolCalls={[
          started,
          {
            id: "2",
            name: "check_task",
            args: { task_id: "t1" },
            status: "completed",
            result: "Task: t1\nSubagent: support-desk\nStatus: completed\nResult: Refund issued",
          },
        ]}
        agents={AGENTS}
      />,
    );

    expect(screen.getByText("Refund issued")).toBeInTheDocument();
  });
});

describe("a coding agent's task under an answer", () => {
  function coded(id: string, result: string, status: ToolCall["status"] = "completed"): ToolCall {
    return { id, name: "run_coding_agent", args: { task: "Build a landing page" }, result, status };
  }
  const report = (outcome: string, harness = "codex") =>
    JSON.stringify({
      kind: "coding_agent",
      harness,
      access: "edit",
      outcome,
      answer: "Built index.html",
      steps: [
        { kind: "edit", title: "/workspace/index.html" },
        { kind: "command", title: "python3 check.py", failed: true },
      ],
    });

  it("is an exchange with Codex, with its brief, answer and every step", async () => {
    render(<TurnDelegations toolCalls={[coded("1", report("completed"))]} agents={AGENTS} />);

    expect(screen.getByText("Talked it through with Codex · 1 exchange")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));
    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Build a landing page")).toBeInTheDocument();
    expect(within(sheet).getByText("Built index.html")).toBeInTheDocument();
    expect(within(sheet).getByText("index.html")).toBeInTheDocument();
    expect(within(sheet).getByText("python3 check.py")).toBeInTheDocument();
  });

  it("names Claude Code, and reads a failed task as failed", async () => {
    render(
      <TurnDelegations
        toolCalls={[coded("1", report("timed_out", "claude_code"))]}
        agents={AGENTS}
      />,
    );
    expect(screen.getByText("Talked it through with Claude Code · 1 exchange")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the exchanges with the team" }));
    expect(within(screen.getByRole("dialog")).getByText(/^failed/)).toBeInTheDocument();
  });

  it("reads a refusal the tool answered with as the answer, and skips one still running", async () => {
    const { rerender } = render(
      <TurnDelegations
        toolCalls={[coded("1", "Codex is not installed in this sandbox's runtime.", "error")]}
        agents={AGENTS}
      />,
    );
    expect(
      screen.getByText("Talked it through with Coding agent · 1 exchange"),
    ).toBeInTheDocument();

    rerender(<TurnDelegations toolCalls={[coded("2", "", "running")]} agents={AGENTS} />);
    expect(screen.queryByText(/Talked it through/)).toBeNull();
  });
});
