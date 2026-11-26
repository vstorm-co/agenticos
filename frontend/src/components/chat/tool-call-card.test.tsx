import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToolCallCard } from "./tool-call-card";
import type { ToolCall } from "@/types";

// A live preview fetches a signed address; what is under test is the card around it.
vi.mock("@/components/artifacts/artifact-thumbnail", () => ({
  ArtifactThumbnail: () => null,
}));

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
// The table view reads its table through the query layer; here only which view opens matters.
vi.mock("./tool-results/table-call", () => ({
  TableToolResult: ({ toolName }: { toolName: string }) => (
    <div data-testid="table-call">{toolName}</div>
  ),
}));
const servers = vi.hoisted(() => ({ list: [] as { name: string; url: string }[] }));
vi.mock("@/hooks", () => ({
  useMcpToolServers: () => servers.list,
  useConversationWorkspace: () => ({ workspace: null, isLoading: false, error: null }),
  useFileActions: () => ({ download: () => {}, openInNewTab: () => {}, error: null }),
}));

function card(overrides: Partial<ToolCall> = {}) {
  return render(
    <ToolCallCard
      mcpServers={servers.list}
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
const open = () => userEvent.click(row());

describe("a tool call in the transcript", () => {
  it("serializes an object result only when opened and retains it across unrelated renders", async () => {
    const serialize = vi.fn(() => ({ detail: "Large tool result" }));
    const result = { toJSON: serialize };
    const toolCall: ToolCall = {
      id: "large",
      name: "post_invoice",
      args: {},
      status: "completed",
      result,
    };
    const { rerender } = render(<ToolCallCard toolCall={toolCall} mcpServers={servers.list} />);
    expect(serialize).not.toHaveBeenCalled();
    await open();
    expect(serialize).toHaveBeenCalledTimes(1);
    rerender(<ToolCallCard toolCall={{ ...toolCall }} mcpServers={servers.list} />);
    expect(serialize).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Large tool result/)).toBeInTheDocument();
  });
  it("narrates what the agent is doing while the tool runs", () => {
    card({ name: "search_documents", status: "running", result: undefined });

    expect(screen.getByText("Searching the documents")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("treats a call that has not started as one in flight", () => {
    card({ status: "pending", result: undefined });

    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("shows a call whose arguments are still streaming as running, with no byte count", () => {
    // "185 B so far" beside the step said nothing a reader could use.
    card({ name: "write_file", status: "pending", result: undefined });

    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.queryByText(/so far/)).toBeNull();
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
    expect(screen.queryByText("Running")).toBeNull();
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
    expect(screen.queryByText("Running")).toBeNull();
  });

  it.each(["pending", "running"] as const)(
    "does not claim to wait for the person while a question is %s",
    (status) => {
      card({ name: "ask_user_question", args: {}, status, result: undefined });
      expect(screen.getByText("Question for you")).toBeVisible();
      expect(screen.queryByText("Waiting for your answer")).not.toBeInTheDocument();
    },
  );

  it("distinguishes separate waiting calls by the questions they ask", () => {
    card({
      id: "plans",
      name: "ask_user_question",
      args: { questions: [{ question: "Which plans?" }] },
      status: "awaiting_answer",
      result: undefined,
    });
    card({
      id: "schedule",
      name: "ask_user_question",
      args: { questions: [{ question: "When should it run?" }] },
      status: "awaiting_answer",
      result: undefined,
    });
    expect(screen.getByRole("button", { name: /Question for you\s*Which plans\?/ })).toBeVisible();
    expect(
      screen.getByRole("button", { name: /Question for you\s*When should it run\?/ }),
    ).toBeVisible();
  });

  it("lets a question waiting on its person say so once, not as an approval", () => {
    // The question is identified by its subject; it is not an approval decision.
    card({
      name: "ask_user_question",
      args: { questions: [{ header: "Plans", question: "Which plans?" }] },
      status: "awaiting_answer",
      result: undefined,
    });

    expect(screen.getByText("Question for you")).toBeInTheDocument();
    expect(screen.queryByText("waiting for approval")).toBeNull();
  });

  it("says a replayed call that never finished in the past tense, without a spinner", () => {
    // The step of an expired approval, or of a run that broke mid-call. Nothing
    // on this screen can finish it, so an animation promises a result that is
    // never coming - it pulsed forever under a conversation that ended days ago.
    card({ name: "search_documents", status: "unfinished", result: undefined });

    expect(screen.queryByText("Searching the documents")).toBeNull();
    expect(screen.getByText("Knowledge Base Search")).toBeInTheDocument();
    expect(screen.queryByText("Running")).toBeNull();
    expect(screen.queryByLabelText("Failed")).toBeNull();
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
      [
        { name: "search_documents", result: "[1] Source: a.md (score: 0.5)\nx" },
        "Knowledge Base Search",
      ],
      [
        { name: "web_search", result: JSON.stringify({ kind: "web_search", results: [] }) },
        "Web Search",
      ],
      [{ name: "create_chart", result: "the tool failed to draw one" }, "Chart"],
      [
        {
          name: "generate_image",
          result: JSON.stringify({
            kind: "generated_image",
            filename: "x_image.png",
            prompt: "a cat",
          }),
        },
        "Image",
      ],
      [{ name: "delegate", args: {} }, "Delegate"],
      [{ name: "run_python", args: { code: "x=1" }, result: "result: 1" }, "Run Python"],
      [{ name: "load_capability", args: { id: "refund-policy" } }, "refund-policy"],
      [{ name: "load_capability", args: {} }, "Read Skill"],
      [{ name: "read_skill", args: { id: "refund-policy" } }, "refund-policy"],
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
});

describe("diagnostic details", () => {
  it("humanises a tool nobody named", () => {
    // A capability added by a backend release has to read sensibly with no
    // frontend change at all.
    card({ name: "issue_invoice" });

    expect(screen.getByText("Issue Invoice")).toBeInTheDocument();
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
      name: "web_search",
      args: { query: "refund law" },
      result: JSON.stringify({ kind: "web_search", results: [] }),
    });
    expect(screen.getByText("refund law")).toBeInTheDocument();
    unmount();

    // A URL is the other subject worth repeating, and after #144 only a tool this side
    // has never heard of carries one - every registered tool takes a path or a query.
    card({ name: "http_request", args: { url: "https://acme.example/help" } });
    expect(screen.getByText("https://acme.example/help")).toBeInTheDocument();
  });

  it("keeps the search subject visible while the tool is running", () => {
    // The caption already occupies that line.
    card({ name: "web_search", args: { query: "refund law" }, status: "running" });

    expect(screen.getByText("refund law")).toBeVisible();
  });

  it("opens and closes on the row", async () => {
    card({ result: "the output" });
    expect(screen.queryByText("the output")).toBeNull();

    await open();
    expect(screen.getByText("the output")).toBeInTheDocument();

    await open();
    expect(screen.queryByText("the output")).toBeNull();
  });
});
describe("one agent asking another", () => {
  const asking = (overrides: Partial<ToolCall> = {}) =>
    render(
      <ToolCallCard
        mcpServers={[]}
        agents={[
          { id: "a-fin", slug: "finance-analyst", name: "Finance Analyst", has_avatar: false },
        ]}
        toolCall={{
          id: "t1",
          name: "task",
          args: { subagent_type: "finance-analyst", description: "Where does MRR stand?" },
          status: "completed",
          result: "MRR is €153k.",
          ...overrides,
        }}
      />,
    );

  it("names the agent that was asked, by the name it goes by", () => {
    asking();

    expect(screen.getByRole("button", { name: /Asked Finance Analyst/ })).toBeInTheDocument();
  });

  it("says it is still asking while the delegate works", () => {
    asking({ status: "running", result: undefined });

    expect(screen.getByText("Asking Finance Analyst")).toBeInTheDocument();
  });

  it("says the person stopped it rather than asking on under a stopped turn", () => {
    asking({ status: "unfinished", result: undefined });

    expect(screen.getByText("Stopped asking Finance Analyst")).toBeInTheDocument();
    expect(screen.queryByText("Asking Finance Analyst")).toBeNull();
  });

  it("opens onto the brief and the answer, folding a long brief", async () => {
    asking();

    await userEvent.click(screen.getByRole("button", { name: /Asked Finance Analyst/ }));

    expect(screen.getByText(/"description": "Where does MRR stand\?/)).toBeInTheDocument();
    expect(screen.getByText("MRR is €153k.")).toBeInTheDocument();
  });

  it("names a delegate the reader cannot see from its handle, without a brief it never got", async () => {
    asking({ args: { subagent_type: "quarterly-report-researcher" }, result: "" });

    await userEvent.click(
      screen.getByRole("button", { name: /Asked Quarterly report researcher/ }),
    );

    expect(screen.queryByText("Brief")).toBeNull();
    expect(screen.queryByText("Answer")).toBeNull();
  });
});

it.each([
  "recall",
  "create_chart",
  "generate_image",
  "generate_speech",
  "generate_video",
  "search_documents",
  "web_search",
  "read_file",
  "execute",
  "run_python",
  "table_query",
  "ask_user_question",
])("shows %s as raw diagnostics without a second visualization", async (name) => {
  const result = JSON.stringify({
    kind: "chart",
    title: "Only in the transcript",
    series: [],
    items: ["profile role"],
  });
  card({ name, args: { query: "profile job-title role" }, result });
  expect(row()).toHaveAttribute("aria-expanded", "false");
  await open();
  expect(screen.getByText(/"query": "profile job-title role"/)).toBeVisible();
  expect(screen.getByText(result)).toBeVisible();
  expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  expect(screen.queryByText("Your memory")).not.toBeInTheDocument();
  await open();
  expect(row()).toHaveAttribute("aria-expanded", "false");
});
it("keeps explicit expansion across completion without opening other steps", async () => {
  const call: ToolCall = { id: "a", name: "run_python", args: {}, status: "running" };
  const view = render(<ToolCallCard toolCall={call} mcpServers={[]} />);
  expect(row()).toHaveAttribute("aria-expanded", "false");
  view.rerender(
    <ToolCallCard toolCall={{ ...call, status: "completed", result: "done" }} mcpServers={[]} />,
  );
  expect(row()).toHaveAttribute("aria-expanded", "false");
  await open();
  expect(screen.getByText("done")).toBeVisible();
});
it.each([undefined, "", { id: 7 }])("handles empty and structured results", async (result) => {
  card({ result });
  await open();
  expect(screen.queryByText("undefined")).not.toBeInTheDocument();
  if (typeof result === "object") expect(screen.getByText(/"id": 7/)).toBeVisible();
});
it("serializes large result payloads only on explicit expansion", async () => {
  const result = { payload: "x".repeat(100_000) };
  const stringify = vi.spyOn(JSON, "stringify");
  try {
    card({ result });
    expect(stringify.mock.calls.filter(([value]) => value === result)).toHaveLength(0);
    await open();
    expect(stringify.mock.calls.filter(([value]) => value === result)).toHaveLength(1);
  } finally {
    stringify.mockRestore();
  }
});
