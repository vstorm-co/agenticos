import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceToolResult, isWorkspaceTool } from "./workspace";
import type { ToolCall } from "@/types";

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "t-1",
    name: "write_file",
    args: { path: "/workspace/test.md", content: "hej" },
    status: "completed",
    ...overrides,
  };
}

/**
 * A sandbox tool call as something a person can read.
 *
 * What this replaces: `{"path": "test.md", "content": "hej"}` printed above `Wrote 1
 * lines to /workspace/test.md`. Everything needed to understand the call was on
 * screen and none of it was legible — so the path becomes a heading, the content a
 * code block, and a listing a list.
 */
describe("a workspace tool call", () => {
  it("leads with the path, not with the arguments", () => {
    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines to /workspace/test.md" />,
    );

    expect(screen.getByText("/workspace/test.md")).toBeVisible();
    expect(screen.queryByText(/"content"/)).toBeNull();
  });

  it("shows what was written, with a way to copy it", () => {
    render(<WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" />);

    expect(screen.getByText("hej")).toBeVisible();
    expect(screen.getByRole("button", { name: /copy/i })).toBeVisible();
  });

  it("shows an edit's replacement, which is the part worth reading", () => {
    // An edit is a diff by intent; the whole file is one click away in the panel.
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "edit_file", args: { path: "/a.py", new_string: "print(2)" } })}
        resultText="Edited /a.py"
      />,
    );

    expect(screen.getByText("print(2)")).toBeVisible();
  });

  it("says what a command was, rather than showing its JSON", () => {
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "execute", args: { command: "pytest -q" } })}
        resultText="12 passed"
      />,
    );

    expect(screen.getByText("pytest -q")).toBeVisible();
    expect(screen.getByText("12 passed")).toBeVisible();
  });

  it("renders a listing as a list", () => {
    // Fifty paths in a code block is a wall; fifty rows is something an eye can
    // scan for the one it wanted.
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "ls", args: { path: "/" } })}
        resultText={"/a.txt\n/b.txt\n"}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("says how many paths it did not show rather than truncating in silence", () => {
    const many = Array.from({ length: 60 }, (_, index) => `/file-${index}.txt`).join("\n");

    render(
      <WorkspaceToolResult
        toolCall={call({ name: "glob", args: { pattern: "**/*.txt" } })}
        resultText={many}
      />,
    );

    expect(screen.getByText(/and 10 more/)).toBeVisible();
  });

  it("names what a search was looking for and where", () => {
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "grep", args: { pattern: "TODO", path: "/src" } })}
        resultText="/src/a.py:3: TODO"
      />,
    );

    expect(screen.getByText("TODO in /src")).toBeVisible();
  });

  it("says it is running rather than showing an empty result", () => {
    render(<WorkspaceToolResult toolCall={call({ status: "running" })} resultText="" />);

    expect(screen.getByText("Running…")).toBeVisible();
  });

  it("marks a refusal as one, because a tool that failed did not do the thing", () => {
    render(
      <WorkspaceToolResult
        toolCall={call({ status: "error" })}
        resultText="path must be absolute"
      />,
    );

    const message = screen.getByText("path must be absolute");
    expect(message.className).toContain("text-destructive");
  });

  it("shortens a very long return line instead of filling the card", () => {
    render(<WorkspaceToolResult toolCall={call({ args: {} })} resultText={"x".repeat(500)} />);

    expect(screen.getByText(/x…$/)).toBeVisible();
  });

  it("draws nothing about a path when the call carried none", () => {
    render(<WorkspaceToolResult toolCall={call({ args: {} })} resultText="done" />);

    expect(screen.getByText("done")).toBeVisible();
  });

  it("claims only the sandbox tools", () => {
    // Anything else has to keep falling through to its own renderer.
    expect(isWorkspaceTool("write_file")).toBe(true);
    expect(isWorkspaceTool("run_python")).toBe(false);
  });
});
