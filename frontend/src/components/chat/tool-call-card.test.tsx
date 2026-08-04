import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToolCallCard } from "./tool-call-card";
import type { ToolCall } from "@/types";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));
// Recharts measures the DOM; what this file cares about is whether a chart is
// rendered at all, and with which spec.
vi.mock("./chart-message", async () => {
  const actual = await vi.importActual<typeof import("./chart-message")>("./chart-message");
  return {
    ...actual,
    ChartMessage: ({ spec }: { spec: { title?: string } }) => (
      <div data-testid="chart">{spec.title}</div>
    ),
  };
});
const servers = vi.hoisted(() => ({ list: [] as { name: string; url: string }[] }));
vi.mock("@/hooks", () => ({
  useMcpToolServers: () => servers.list,
  useConversationWorkspace: () => ({ workspace: null, isLoading: false, error: null }),
  useFileDownload: () => ({ download: () => {}, error: null }),
}));

function card(overrides: Partial<ToolCall> = {}) {
  return render(
    <ToolCallCard
      toolCall={{
        id: "tc-1",
        name: "post_invoice",
        args: {},
        status: "completed",
        result: "done",
        ...overrides,
      }}
    />,
  );
}

/** The step's own row, which is the toggle when there is anything to open. */
const row = () => screen.getAllByRole("button")[0]!;
const raw = () => screen.getByRole("button", { name: /raw output|formatted view/ });
const open = () => userEvent.click(row());

/**
 * One tool call in the transcript.
 *
 * A step in a narration, not a card: while the tool runs the line says what the agent
 * is doing, and once it finishes it says what happened. That switch is the whole
 * design - "Writing test1.md" is useful while it is true and misleading afterwards.
 *
 * Collapsed by default, because a transcript of expanded tool calls is a transcript
 * nobody scrolls. The exceptions are the calls whose whole value is the thing they
 * produced: a chart, a question waiting on an answer, code that ran, a file written.
 */
describe("a tool call in the transcript", () => {
  it("narrates what the agent is doing while the tool runs", () => {
    card({ name: "search_documents", status: "running", result: undefined });

    expect(screen.getByText("Searching the documents")).toBeInTheDocument();
    expect(screen.getByLabelText("Running")).toBeInTheDocument();
  });

  it("treats a call that has not started as one in flight", () => {
    card({ status: "pending", result: undefined });

    expect(screen.getByLabelText("Running")).toBeInTheDocument();
  });

  it("says what happened once the call has finished, rather than narrating it", () => {
    card({ name: "search_documents", result: "[1] Source: a.md (score: 0.5)\nBody." });

    expect(screen.queryByText("Searching the documents")).toBeNull();
    expect(screen.getByText("Knowledge Base Search")).toBeInTheDocument();
  });

  it("marks nothing on a step that simply worked", () => {
    // A tick on every row is a tick that says nothing. What earns a marker is the
    // exception - and that is the difference between a narration and a checklist.
    card({ result: "done" });

    expect(screen.queryByLabelText("Failed")).toBeNull();
    expect(screen.queryByLabelText("Running")).toBeNull();
  });

  it("marks a tool that failed", () => {
    card({ status: "error", result: "boom" });

    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
  });

  it("says a parked call is waiting rather than showing it as running", () => {
    // A call awaiting approval produces no result at all until somebody decides, so a
    // spinner on it is a lie that never resolves.
    card({ status: "awaiting_approval", result: undefined });

    expect(screen.getByText("waiting for approval")).toBeInTheDocument();
    expect(screen.queryByLabelText("Running")).toBeNull();
  });

  it("reads a workspace call as a sentence about the file", () => {
    const { unmount } = card({
      name: "write_file",
      args: { path: "/workspace/test1.md", content: "hej" },
      status: "running",
      result: undefined,
    });
    expect(screen.getByText("Writing test1.md")).toBeInTheDocument();
    unmount();

    card({ name: "write_file", args: { path: "/workspace/test1.md", content: "hej" } });
    expect(screen.getByText("Wrote test1.md")).toBeInTheDocument();
  });

  it("names each tool that has a renderer of its own", () => {
    const cases: [Partial<ToolCall>, string][] = [
      [{ name: "get_current_datetime", result: "Current date: 2026-07-31" }, "Current Date & Time"],
      [
        { name: "search_knowledge_base", result: "[1] Source: a.md (score: 0.5)\nx" },
        "Knowledge Base Search",
      ],
      [
        { name: "web_search_tool", result: JSON.stringify({ kind: "web_search", results: [] }) },
        "Web Search",
      ],
      [{ name: "fetch_url", args: { url: "https://acme.example/" } }, "Fetched page"],
      [{ name: "run_python", args: { code: "x=1" }, result: "result: 1" }, "Run Python"],
      [{ name: "list_skills", result: "[]" }, "Available Skills"],
      [{ name: "load_skill", args: { skill_name: "refund_policy" } }, "Refund Policy"],
      [{ name: "load_skill", args: {} }, "Load Skill"],
      [{ name: "ls", args: { path: "/workspace" } }, "Listed /workspace"],
      [
        { name: "grep", args: { pattern: "TODO", path: "/workspace/app.py" } },
        "Searched for TODO in app.py",
      ],
      [{ name: "execute", args: { command: "pytest -q" } }, "Ran pytest -q"],
    ];

    for (const [toolCall, expected] of cases) {
      const { unmount } = card(toolCall);
      expect(screen.getAllByText(expected)[0], expected).toBeInTheDocument();
      unmount();
    }
  });

  it("humanises a tool nobody named", () => {
    // A capability added by a backend release has to read sensibly with no
    // frontend change at all.
    card({ name: "post_invoice_tool" });

    expect(screen.getByText("Post Invoice")).toBeInTheDocument();
  });

  it("names an MCP call by its server and what was asked of it", () => {
    // Nothing on a tool call says where it came from; the connection's name is the
    // prefix the backend put on it, so matching that is what turns
    // `linear_create_issue` into something a person reads.
    servers.list = [{ name: "Linear", url: "https://mcp.linear.app/sse" }];

    card({ name: "linear_create_issue", args: { title: "Fix the sweep" } });

    expect(screen.getByText("Linear · Create issue")).toBeInTheDocument();
    servers.list = [];
  });

  it("falls back to the humanised name when no server claims the prefix", () => {
    // A server deleted since the turn ran, or one this caller cannot list. The step
    // still reads as English; it just does not name the product.
    servers.list = [{ name: "GitHub", url: "https://api.githubcopilot.com/mcp/" }];

    card({ name: "linear_create_issue", args: {} });

    expect(screen.getByText("Linear Create Issue")).toBeInTheDocument();
    servers.list = [];
  });

  it("shows the query or the URL beside a finished call", () => {
    // Three calls in a row all called "Web Search" are indistinguishable without it.
    const { unmount } = card({
      name: "search_web",
      args: { query: "refund law" },
      result: JSON.stringify({ kind: "web_search", results: [] }),
    });
    expect(screen.getByText("refund law")).toBeInTheDocument();
    unmount();

    card({ name: "fetch_url", args: { url: "https://acme.example/help" } });
    expect(screen.getByText("https://acme.example/help")).toBeInTheDocument();
  });

  it("says nothing about the input while the tool is still running", () => {
    // The caption already occupies that line.
    card({ name: "search_web", args: { query: "refund law" }, status: "running" });

    expect(screen.queryByText("refund law")).toBeNull();
  });

  it("opens and closes on the row", async () => {
    card({ result: "the output" });
    expect(screen.queryByText("the output")).toBeNull();

    await open();
    expect(screen.getByText("the output")).toBeInTheDocument();

    await open();
    expect(screen.queryByText("the output")).toBeNull();
  });

  it("is a button, so a keyboard opens it without a handler of its own", () => {
    // The row used to be a div with a button role and hand-rolled Enter/Space keys.
    card({ result: "the output" });

    expect(row().tagName).toBe("BUTTON");
    expect(row()).toHaveAttribute("aria-expanded", "false");
  });

  it("gives a step with nothing to open no toggle at all", () => {
    // `list_skills` answers with a prompt fragment the model reads and a person does
    // not, so the row is a statement rather than a control.
    card({ name: "list_skills", result: JSON.stringify([{ name: "refunds" }]) });

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText("Available Skills")).toBeInTheDocument();
  });

  it("opens a question without being asked, because it is a control", () => {
    card({ name: "ask_user", args: { questions: [{ question: "Which?" }] }, result: "" });

    expect(screen.getByText("Which?")).toBeInTheDocument();
  });

  it("opens the newest turn's last call, which is the result somebody came back for", () => {
    // Probed by the card's own control rather than by the written text: a finished
    // write no longer repeats its contents under a card that opens the file, so
    // "hej" is absent by design and would make this assert the opposite of expansion.
    render(
      <ToolCallCard
        startOpen
        conversationId="c-1"
        toolCall={{
          id: "tc-1",
          name: "write_file",
          args: { path: "notes.md", content: "hej" },
          status: "completed",
          result: "Wrote 1 lines",
        }}
      />,
    );

    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
  });

  it("leaves an older call read back from history folded", () => {
    // Opening every finished call on mount turned a conversation somebody reopened
    // into a wall of results they came back for none of.
    const chart = card({
      name: "create_chart_tool",
      result: JSON.stringify({ kind: "chart", title: "Spend", series: [] }),
    });
    expect(screen.queryByTestId("chart")).toBeNull();
    chart.unmount();

    const python = card({ name: "run_python", args: { code: "print(1)" }, result: "stdout:\n1" });
    expect(screen.queryByTestId("markdown")).toBeNull();
    python.unmount();

    card({
      name: "write_file",
      args: { path: "notes.md", content: "hej" },
      result: "Wrote 1 lines",
    });
    expect(screen.queryByText("hej")).toBeNull();
  });

  it("opens what a call produced while somebody was watching it happen", () => {
    // The live case: the step mounts running and finishes on screen. A file written in
    // front of somebody is the answer to what they asked for.
    const live = { id: "tc-1", name: "write_file", args: { path: "notes.md", content: "hej" } };
    const { rerender } = render(
      <ToolCallCard conversationId="c-1" toolCall={{ ...live, status: "running" }} />,
    );
    expect(screen.queryByRole("button", { name: "Open" })).toBeNull();

    rerender(
      <ToolCallCard
        conversationId="c-1"
        toolCall={{ ...live, status: "completed", result: "Wrote 1 lines" }}
      />,
    );

    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
  });

  it("leaves code that is still running collapsed", () => {
    card({ name: "run_python", args: { code: "print(1)" }, status: "running", result: undefined });

    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("leaves a chart result that is not a chart collapsed", () => {
    card({ name: "create_chart_tool", result: "the tool failed to draw one" });

    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("opens a chart that finishes after the step was already on screen", () => {
    // The same live rule, for the tool whose whole value is the picture.
    const { rerender } = render(
      <ToolCallCard
        toolCall={{ id: "tc-1", name: "create_chart_tool", args: {}, status: "running" }}
      />,
    );
    expect(screen.queryByTestId("chart")).toBeNull();

    rerender(
      <ToolCallCard
        toolCall={{
          id: "tc-1",
          name: "create_chart_tool",
          args: {},
          status: "completed",
          result: JSON.stringify({ kind: "chart", title: "Spend", series: [] }),
        }}
      />,
    );

    expect(screen.getByTestId("chart")).toHaveTextContent("Spend");
  });

  it("swaps the formatted view for the raw one", async () => {
    // The escape hatch: whatever a renderer decided to show, this is what the tool
    // actually said.
    card({ args: { invoice_id: 7 }, result: "done" });
    await open();

    await userEvent.click(raw());

    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText(/"invoice_id": 7/)).toBeInTheDocument();
  });

  it("keeps the step open when the raw view is toggled", async () => {
    card({ args: { invoice_id: 7 }, result: "done" });
    await open();

    await userEvent.click(raw());

    expect(row()).toHaveAttribute("aria-expanded", "true");
  });

  it("goes back to the formatted view", async () => {
    card({
      name: "get_current_datetime",
      args: { timezone: "UTC" },
      result: "Current date: 2026-07-31",
    });
    await open();
    await userEvent.click(raw());
    expect(screen.getByText("Arguments")).toBeInTheDocument();

    await userEvent.click(raw());

    expect(screen.queryByText("Arguments")).toBeNull();
    expect(screen.getByText("2026-07-31")).toBeInTheDocument();
  });

  it("forgets the raw view when the step is closed", async () => {
    // Reopening on raw output would be a state nobody asked for twice.
    card({ result: "done" });
    await open();
    await userEvent.click(raw());

    await open();
    await open();

    expect(screen.queryByText("Arguments")).toBeNull();
  });

  it("offers no raw view until the step is open", () => {
    // It is an escape hatch for somebody already looking at a call, not a control on
    // every line of the transcript.
    card({ result: "done" });

    expect(screen.queryByRole("button", { name: /raw output/ })).toBeNull();
  });

  it("hands each renderer what it needs, once opened", async () => {
    const cases: [Partial<ToolCall>, string][] = [
      [{ name: "get_current_datetime", result: "Current date: 2026-07-31" }, "2026-07-31"],
      [
        { name: "search_documents", result: "[1] Source: a.md (score: 0.9)\nA passage." },
        "A passage.",
      ],
      [
        {
          name: "web_search_tool",
          result: JSON.stringify({
            kind: "web_search",
            results: [{ title: "Hit", url: "https://a.example/" }],
          }),
        },
        "Hit",
      ],
      [{ name: "fetch_url", args: { url: "https://acme.example/" }, result: "" }, "acme.example"],
      [
        { name: "load_skill", result: "<description>How refunds work.</description>" },
        "How refunds work.",
      ],
      [{ name: "post_invoice", result: "Posted." }, "Posted."],
      [{ name: "read_file", args: { path: "a.txt" }, result: "the contents" }, "the contents"],
      [{ name: "execute", args: { command: "ls" }, result: "a.txt" }, "a.txt"],
    ];

    for (const [toolCall, expected] of cases) {
      const { unmount } = card(toolCall);
      await open();
      expect(screen.getAllByText(expected)[0], expected).toBeInTheDocument();
      unmount();
    }
  });

  it("renders a structured result as JSON rather than as [object Object]", async () => {
    // A tool can return an object; the raw view and the generic view both have to
    // make text of it.
    card({ result: { id: 7 } as never });

    await open();

    expect(screen.getByText(/"id": 7/)).toBeInTheDocument();
  });

  it("shows an empty result as empty rather than as the word undefined", async () => {
    card({ result: undefined });

    await open();

    expect(screen.queryByText("undefined")).toBeNull();
  });

  it("keeps a fetched page's own renderer even before the page arrives", () => {
    // `fetch_url` is recognised from its arguments rather than its result, so the
    // step can name it while it is still fetching.
    const running = card({
      name: "fetch_url",
      args: { url: "https://acme.example/" },
      status: "running",
    });
    expect(screen.getByText("Reading a web page")).toBeInTheDocument();
    running.unmount();

    // `fetch` is the same renderer under a different name.
    card({
      name: "fetch",
      args: { url: "https://acme.example/" },
      status: "completed",
      result: "",
    });
    expect(screen.getByText("Fetched page")).toBeInTheDocument();
  });
});
