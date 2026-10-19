import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CodingAgentResult, parseCodingReport } from "./coding-agent";
import type { ToolCall } from "@/types";

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "c1",
    name: "run_coding_agent",
    args: { task: "Fix the failing test" },
    status: "completed",
    ...overrides,
  } as ToolCall;
}

const REPORT = {
  kind: "coding_agent",
  harness: "claude_code",
  access: "edit",
  outcome: "completed",
  answer: "Fixed **the off-by-one**.",
  session_id: "s-1",
  steps: [
    { kind: "read", title: "app.py" },
    { kind: "command", title: "pytest -q", failed: true },
    { kind: "edit", title: "app.py" },
  ],
  files_changed: ["app.py"],
  refused: ["WebFetch"],
};

describe("CodingAgentResult", () => {
  it("shows the harness, what it answered and the files it changed", async () => {
    render(<CodingAgentResult toolCall={call()} resultText={JSON.stringify(REPORT)} />);

    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(await screen.findByText("the off-by-one")).toBeInTheDocument();
    expect(screen.getByText("Changed 1 file:")).toBeInTheDocument();
    expect(screen.getByText("Not allowed read-only: WebFetch")).toBeInTheDocument();
  });

  it("lists every step, a failed one marked as failed", async () => {
    render(<CodingAgentResult toolCall={call()} resultText={JSON.stringify(REPORT)} />);

    await userEvent.click(screen.getByRole("button", { name: /3 steps/ }));

    expect(screen.getByText("pytest -q")).toBeInTheDocument();
    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Read")).toBeInTheDocument();
    expect(screen.getByLabelText("Edited")).toBeInTheDocument();
  });

  it("names the harness that did it and says when a task ran out of time", () => {
    const { rerender } = render(
      <CodingAgentResult
        toolCall={call()}
        resultText={JSON.stringify({
          kind: "coding_agent",
          harness: "codex",
          access: "edit",
          outcome: "completed",
          answer: "Done it",
        })}
      />,
    );
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();

    rerender(
      <CodingAgentResult
        toolCall={call()}
        resultText={JSON.stringify({ ...REPORT, outcome: "timed_out", steps: [] })}
      />,
    );
    expect(screen.getByText("Stopped: out of time")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /steps/ })).toBeNull();
  });

  it("shows a refusal as the sentence it is, with the task open above it", () => {
    render(
      <CodingAgentResult
        toolCall={call()}
        resultText="Claude Code is not installed in this sandbox's runtime."
      />,
    );
    expect(screen.getByText("Fix the failing test")).toBeInTheDocument();
    expect(screen.getByText(/is not installed/)).toBeInTheDocument();
  });

  it("shows nothing but the task while it runs, and nothing at all without one", () => {
    const { container, rerender } = render(
      <CodingAgentResult toolCall={call({ status: "running" })} resultText="" />,
    );
    expect(screen.getByText("Fix the failing test")).toBeInTheDocument();

    rerender(<CodingAgentResult toolCall={call({ args: {} })} resultText="" />);
    expect(container).toHaveTextContent(/^$/);
  });
});

describe("parseCodingReport", () => {
  it("reads only a coding agent's report", () => {
    expect(parseCodingReport(JSON.stringify(REPORT))?.harness).toBe("claude_code");
    expect(parseCodingReport(JSON.stringify({ kind: "generated_image" }))).toBeNull();
    expect(parseCodingReport("[1]")).toBeNull();
    expect(parseCodingReport("null")).toBeNull();
    expect(parseCodingReport("not json")).toBeNull();
    expect(parseCodingReport(JSON.stringify({ answer: "no harness" }))).toBeNull();
  });

  it("reads a report stored before its kind reached the wire", () => {
    const { kind: _kind, ...stored } = REPORT;
    expect(parseCodingReport(JSON.stringify(stored))).toMatchObject({
      kind: "coding_agent",
      harness: "claude_code",
    });
  });
});
