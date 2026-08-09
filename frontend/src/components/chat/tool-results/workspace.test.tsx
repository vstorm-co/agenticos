import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceToolResult, isWorkspaceTool } from "./workspace";
import type { ToolCall } from "@/types";

const state = vi.hoisted(() => ({
  items: [] as { path: string; size: number | null; is_dir: boolean }[],
  downloaded: [] as string[],
  downloadError: null as string | null,
}));

vi.mock("@/hooks", () => ({
  useConversationWorkspace: () => ({
    workspace: {
      scope: "conversation",
      backend: "state",
      owner_label: "This conversation",
      items: state.items,
      total: state.items.length,
      bytes_total: 0,
      unreadable_reason: null,
    },
    isLoading: false,
    error: null,
    refresh: async () => {},
  }),
  useFileActions: (access: { path: string }) => ({
    download: () => state.downloaded.push(access.path),
    openInNewTab: () => {},
    error: state.downloadError,
  }),
}));
vi.mock("@/lib/workspace-files", () => ({
  workspaceFileAccess: (_source: unknown, path: string) => ({
    path,
    textKey: ["text", path],
    bytesKey: ["bytes", path],
  }),
}));
// The card's job is to open the shared viewer on the right file. What that viewer
// then shows is asserted where it lives, once, rather than through every surface
// that opens it.
vi.mock("@/components/files", () => ({
  FileIcon: () => <span data-testid="icon" />,
  FileViewer: ({ file, onClose }: { file: { path?: string | null }; onClose: () => void }) => (
    <div data-testid="viewer">
      {file.path}
      <button type="button" onClick={onClose}>
        close the viewer
      </button>
    </div>
  ),
}));

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "t-1",
    name: "write_file",
    args: { path: "/workspace/test.md", content: "hej" },
    status: "completed",
    ...overrides,
  };
}

beforeEach(() => {
  state.items = [{ path: "/test.md", size: 3, is_dir: false }];
  state.downloaded = [];
  state.downloadError = null;
});

/**
 * What a workspace tool call opens into.
 *
 * The step above it already says *Wrote test.md*, so this is not a place for a second
 * label - it is the thing the call produced: a file to open, the text that was
 * written, a listing, a command's output. What it replaces printed
 * `{"path": "test.md", "content": "hej"}` above `Wrote 1 lines to /workspace/test.md`
 * and left the reader to work out which was which.
 */
describe("a workspace tool call", () => {
  it("ends a write in a file somebody can open, not a sentence about one", () => {
    render(
      <WorkspaceToolResult
        toolCall={call()}
        resultText="Wrote 1 lines to /workspace/test.md"
        conversationId="c-1"
      />,
    );

    expect(screen.getByText("test.md")).toBeVisible();
    expect(screen.getByText(/Markdown · MD/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open" })).toBeVisible();
    expect(screen.queryByText(/"content"/)).toBeNull();
  });

  it("does not also print the tool's own sentence about the file", () => {
    // "Wrote 1 lines to /workspace/test.md" beside a card naming the file is the same
    // fact told worse.
    render(
      <WorkspaceToolResult
        toolCall={call()}
        resultText="Wrote 1 lines to /workspace/test.md"
        conversationId="c-1"
      />,
    );

    expect(screen.queryByText(/Wrote 1 lines/)).toBeNull();
  });

  it("resolves the file against the conversation's own listing", async () => {
    // The tool is called with `/workspace/test.md` and the workspace stores it as
    // `/test.md`. A button built from the argument opens a file that is not there.
    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(screen.getByTestId("viewer")).toHaveTextContent("/test.md");
  });

  it("saves the file the listing knows about, not the path in the arguments", async () => {
    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    expect(state.downloaded).toEqual(["/test.md"]);
  });

  it("says why a download was refused instead of doing nothing", () => {
    // A binary on a container-backed host is refused by the API, and a button that
    // silently does nothing is the worst way to say so.
    state.downloadError = "This host can only read text";

    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );

    expect(screen.getByText("This host can only read text")).toBeVisible();
  });

  it("offers the controls even when the listing has not caught up", () => {
    // It used to withhold them, reasoning that offering to open a file we cannot
    // confirm is dishonest. But the listing is behind for the whole of the
    // interesting case: a workspace has no committed row until a turn flushes one, so
    // a turn that wrote a file and then parked for approval drew a card with no way
    // to open the file it had just made - and both buttons appeared after a reload.
    //
    // The card is drawn because the write *succeeded*, which is the same evidence the
    // buttons need. A wrong path is a sentence from the viewer, which beats a control
    // that was never offered.
    state.items = [];

    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );

    expect(screen.getByText("test.md")).toBeVisible();
    expect(screen.getByRole("button", { name: "Open" })).toBeVisible();
  });

  it("does not repeat a written file's contents under the card that opens it", () => {
    // It used to paste the whole `content` argument beneath the card. Beside a card
    // that names the file and opens it, that is the same thing told worse: it pushed
    // the rest of the turn off the screen, and what it duplicated was one click away
    // in the card and one more in the step's raw view.
    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );

    expect(screen.getByText("test.md")).toBeVisible();
    expect(screen.queryByText("hej")).toBeNull();
  });

  it("still shows what a failed write tried to put there", () => {
    // No card, because nothing was written - so the argument is the only evidence of
    // what was attempted, and folding it away would leave the turn unexplained.
    render(
      <WorkspaceToolResult
        toolCall={call({ status: "error" })}
        resultText="The workspace is full"
        conversationId="c-1"
      />,
    );

    expect(screen.getByText("hej")).toBeVisible();
    expect(screen.getByRole("button", { name: /copy/i })).toBeVisible();
  });

  it("shows an edit's replacement, which is the part worth reading", () => {
    // An edit is a diff by intent; the whole file is one click away in the viewer.
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "edit_file", args: { path: "/a.py", new_string: "print(2)" } })}
        resultText="Edited /a.py"
        conversationId="c-1"
      />,
    );

    expect(screen.getByText("print(2)")).toBeVisible();
  });

  it("offers no card for a write that failed", () => {
    // There is no file. A card offering to open one is the single wrong thing this
    // could do.
    render(
      <WorkspaceToolResult
        toolCall={call({ status: "error" })}
        resultText="path must be absolute"
        conversationId="c-1"
      />,
    );

    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();
    expect(screen.getByText("path must be absolute").className).toContain("text-destructive");
  });

  it("shows a command and its output, keeping the output's own line breaks", () => {
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "execute", args: { command: "pytest -q" } })}
        resultText={"F\n12 passed"}
      />,
    );

    expect(screen.getByText(/pytest -q/)).toBeVisible();
    const output = screen.getByText(/12 passed/);
    expect(output.className).toContain("whitespace-pre");
  });

  it("shows a read as the file's text", () => {
    render(
      <WorkspaceToolResult
        toolCall={call({ name: "read_file", args: { path: "/a.md" } })}
        resultText="# Title"
      />,
    );

    expect(screen.getByText("# Title")).toBeVisible();
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

  it("says it is running rather than showing an empty result", () => {
    render(<WorkspaceToolResult toolCall={call({ status: "running" })} resultText="" />);

    expect(screen.getByText("Running…")).toBeVisible();
  });

  it("shortens a very long return line instead of filling the transcript", () => {
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

  it("closes the viewer again", async () => {
    // The card opens a modal; the way out has to work, and it is a callback the card
    // owns rather than the viewer.
    render(
      <WorkspaceToolResult toolCall={call()} resultText="Wrote 1 lines" conversationId="c-1" />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Open" }));

    await userEvent.click(screen.getByRole("button", { name: "close the viewer" }));

    expect(screen.queryByTestId("viewer")).toBeNull();
  });

  it("says only that a file with no suffix is a file", () => {
    // `Makefile` has no extension, so the kind line has nothing to append - and
    // nothing to resolve from either. "File" rather than a guess at "Text": an
    // unrecognised name asks for bytes, which is the safe way round, and the label
    // says the same thing the request does.
    render(
      <WorkspaceToolResult
        toolCall={call({ args: { path: "/Makefile", content: "all:" } })}
        resultText="Wrote 1 lines"
        conversationId="c-1"
      />,
    );

    expect(screen.getByText("Makefile")).toBeVisible();
    expect(screen.getByText("File")).toBeVisible();
  });
});
