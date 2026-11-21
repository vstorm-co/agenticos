import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CodingAgentResult, parseCodingReport } from "./coding-agent";
import type { ToolCall } from "@/types";

vi.mock("./workspace", () => ({
  WorkspaceFileCard: ({ path }: { path: string }) => <p>{`Archive ${path}`}</p>,
}));

vi.mock("./coding-changes", () => ({
  TaskChanges: ({ changeId, conversationId }: { changeId: string; conversationId?: string }) => (
    <p data-origin={conversationId}>{`changes ${changeId}`}</p>
  ),
}));

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

it("keeps undo bound to the coding task's recorded conversation file origin", () => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({ ...REPORT, changes_id: "change-1" })}
      fileSource={{ kind: "conversation", id: "original-chat" }}
    />,
  );
  expect(screen.getByText("changes change-1")).toHaveAttribute("data-origin", "original-chat");
});

describe("CodingAgentResult", () => {
  it("shows the harness, what it answered and the files it changed", async () => {
    render(<CodingAgentResult toolCall={call()} resultText={JSON.stringify(REPORT)} />);

    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(await screen.findByText("the off-by-one")).toBeInTheDocument();
    expect(screen.getByText("Changed 1 file:")).toBeInTheDocument();
    expect(screen.getByText("Not allowed read-only: WebFetch")).toBeInTheDocument();
  });

  it("shows what the task changed, the names kept for a reader the diff is refused to", () => {
    render(
      <CodingAgentResult
        toolCall={call()}
        resultText={JSON.stringify({ ...REPORT, changes_id: "c-1" })}
      />,
    );

    expect(screen.getByText("changes c-1")).toBeInTheDocument();
    expect(screen.queryByText("Changed 1 file:")).not.toBeInTheDocument();
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

it.each([
  [true, "Session: api · continued"],
  [false, "Session: api · new"],
  [undefined, "Session: api"],
])("shows the named personal session and its continuation state", (resumed, label) => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({ ...REPORT, session_name: "api", session_resumed: resumed })}
    />,
  );
  expect(screen.getByText(label)).toBeInTheDocument();
});

it("does not render an invalid session name from stored tool output", () => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({ ...REPORT, session_name: "../private" })}
    />,
  );
  expect(screen.queryByText(/Session:/)).not.toBeInTheDocument();
});

it("shows the personal account, source revision and validated result archive", () => {
  const archive = "coding-results/12345678-1234-1234-1234-123456789abc.zip";
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({
        ...REPORT,
        account_label: "My Claude",
        base_revision: "abcdef1234567890",
        result_archive: archive,
      })}
    />,
  );
  expect(screen.getByText("Personal account: My Claude")).toBeInTheDocument();
  expect(screen.getByText("Workspace snapshot: abcdef123456")).toBeInTheDocument();
  expect(screen.getByText(`Archive ${archive}`)).toBeInTheDocument();
});

it("does not render a result archive outside the private result directory", () => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({
        ...REPORT,
        result_archive: "../private.zip",
      })}
    />,
  );
  expect(screen.queryByText(/Archive /)).not.toBeInTheDocument();
});

it("names custom ACP reports without claiming a built-in provider", () => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({
        kind: "coding_agent",
        harness: "custom",
        access: "edit",
        outcome: "completed",
        answer: "Investigated the module",
      })}
    />,
  );
  expect(screen.getByText("ACP")).toBeInTheDocument();
  expect(screen.getByText("Investigated the module")).toBeInTheDocument();
});

it("shows the registered external runtime name in its result", () => {
  render(
    <CodingAgentResult
      toolCall={call()}
      resultText={JSON.stringify({
        kind: "coding_agent",
        harness: "custom",
        runtime_name: "Antigravity",
        access: "edit",
        outcome: "completed",
        answer: "Done",
      })}
    />,
  );
  expect(screen.getByText("Antigravity")).toBeInTheDocument();
});

it.each([
  { harness: "unknown" },
  { steps: [{ kind: "unknown", title: "read" }] },
  { steps: [{ kind: "read", title: 42 }] },
  { steps: [null] },
  { steps: "read" },
  { files_changed: [42] },
  { refused: [null] },
  { answer: { text: "answer" } },
  { session_resumed: "yes" },
])("rejects malformed owned report fields instead of crashing the conversation: %j", (patch) => {
  const text = JSON.stringify({ ...REPORT, ...patch });
  expect(parseCodingReport(text)).toBeNull();
  render(<CodingAgentResult toolCall={call()} resultText={text} />);
  expect(screen.getByText(text)).toBeVisible();
});

it("reads nullable backend metadata without fetching a null changes id", () => {
  const text = JSON.stringify({
    ...REPORT,
    changes_id: null,
    session_name: null,
    session_resumed: null,
    account_label: null,
    base_revision: null,
    result_archive: null,
    session_id: null,
  });
  expect(parseCodingReport(text)?.changes_id).toBeUndefined();
  render(<CodingAgentResult toolCall={call()} resultText={text} />);
  expect(screen.getByText("Claude Code")).toBeVisible();
  expect(screen.queryByText("changes null")).toBeNull();
});
