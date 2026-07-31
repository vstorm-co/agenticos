import { fireEvent, render, screen, within } from "@testing-library/react";
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

const bar = () => screen.getAllByRole("button")[0]!;
const raw = () => screen.getByRole("button", { name: /raw output|formatted view/ });

/**
 * One tool call in the transcript.
 *
 * The card is a step in a narration: while the tool runs it says what the agent
 * is doing, and once it finishes it says what the tool was. That switch is the
 * whole design - a caption reading "Searching the knowledge base" is useful
 * while it is true and misleading afterwards.
 *
 * Collapsed by default, because a transcript of expanded tool calls is a
 * transcript nobody scrolls. The exceptions are the ones whose whole value is
 * visible: a chart, a question waiting on an answer, and code that ran.
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

  it("names the tool once it has finished, rather than narrating it", () => {
    card({ name: "search_documents", result: "[1] Source: a.md (score: 0.5)\nBody." });

    expect(screen.queryByText("Searching the documents")).toBeNull();
    expect(screen.getByText("Knowledge Base Search")).toBeInTheDocument();
    expect(screen.getByLabelText("Done")).toBeInTheDocument();
  });

  it("marks a tool that failed", () => {
    card({ status: "error", result: "boom" });

    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
    expect(screen.queryByLabelText("Done")).toBeNull();
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
      [{ name: "ask_user", args: { questions: [] }, result: "" }, "Question"],
      [{ name: "run_python", args: { code: "x=1" }, result: "result: 1" }, "Run Python"],
      [{ name: "list_skills", result: "[]" }, "Available Skills"],
      [{ name: "load_skill", args: { skill_name: "refund_policy" } }, "Refund Policy"],
      [{ name: "load_skill", args: {} }, "Load Skill"],
    ];

    for (const [toolCall, expected] of cases) {
      const { unmount } = card(toolCall);
      // Scoped to the bar: a renderer below it may use the same word - `ask_user`
      // labels its own list "Question" too.
      expect(within(bar()).getByText(expected), expected).toBeInTheDocument();
      unmount();
    }
  });

  it("humanises a tool nobody named", () => {
    // A capability added by a backend release has to read sensibly with no
    // frontend change at all.
    card({ name: "post_invoice_tool" });

    expect(screen.getByText("Post Invoice")).toBeInTheDocument();
  });

  it("shows the query or the URL in the collapsed bar", () => {
    // Three tool calls in a row all called "Web Search" are indistinguishable
    // without it.
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

  it("prefers the URL over the query when a tool sent both", () => {
    card({ name: "fetch_url", args: { url: "https://acme.example/", query: "ignored" } });

    expect(screen.getByText("https://acme.example/")).toBeInTheDocument();
    expect(screen.queryByText("ignored")).toBeNull();
  });

  it("says nothing about the input while the tool is still running", () => {
    // The caption already occupies that line.
    card({ name: "search_web", args: { query: "refund law" }, status: "running" });

    expect(screen.queryByText("refund law")).toBeNull();
  });

  it("shows no hint for a tool whose arguments are not a query or a URL", () => {
    card({ args: { invoice_id: 7 } });

    expect(screen.queryByText("7")).toBeNull();
  });

  it("opens and closes on the bar", async () => {
    card({ result: "the output" });
    expect(screen.queryByText("the output")).toBeNull();

    await userEvent.click(bar());
    expect(screen.getByText("the output")).toBeInTheDocument();

    await userEvent.click(bar());
    expect(screen.queryByText("the output")).toBeNull();
  });

  it("opens from the keyboard, on either key that means 'press'", () => {
    // The bar is a div with a button role, so the keys are handled by hand.
    card({ result: "the output" });

    fireEvent.keyDown(bar(), { key: "Enter" });
    expect(screen.getByText("the output")).toBeInTheDocument();

    fireEvent.keyDown(bar(), { key: " " });
    expect(screen.queryByText("the output")).toBeNull();
  });

  it("ignores a key that does not", () => {
    card({ result: "the output" });

    fireEvent.keyDown(bar(), { key: "Escape" });

    expect(screen.queryByText("the output")).toBeNull();
  });

  it("opens a question, a chart and finished code without being asked", () => {
    // Each is worth nothing collapsed.
    const { unmount } = card({
      name: "ask_user",
      args: { questions: [{ question: "Which?" }] },
      result: "",
    });
    expect(screen.getByText("Which?")).toBeInTheDocument();
    unmount();

    const chart = card({
      name: "create_chart_tool",
      result: JSON.stringify({ kind: "chart", title: "Spend", series: [] }),
    });
    expect(screen.getByTestId("chart")).toHaveTextContent("Spend");
    chart.unmount();

    card({ name: "run_python", args: { code: "print(1)" }, result: "stdout:\n1" });
    expect(screen.getByTestId("markdown")).toHaveTextContent("```python");
  });

  it("leaves code that is still running collapsed", () => {
    card({ name: "run_python", args: { code: "print(1)" }, status: "running", result: undefined });

    expect(screen.queryByTestId("markdown")).toBeNull();
  });

  it("leaves a chart result that is not a chart collapsed", () => {
    card({ name: "create_chart_tool", result: "the tool failed to draw one" });

    expect(screen.queryByTestId("chart")).toBeNull();
  });

  it("opens a chart that finishes after the card was already on screen", () => {
    // Live streaming: the card mounts while the tool is running, so the
    // open-by-default never fired.
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

  it("swaps the formatted view for the raw one, and opens the card to show it", async () => {
    // The escape hatch: whatever a renderer decided to show, this is what the tool
    // actually said.
    card({ args: { invoice_id: 7 }, result: "done" });

    await userEvent.click(raw());

    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText(/"invoice_id": 7/)).toBeInTheDocument();
  });

  it("does not toggle the card when the raw button is pressed", async () => {
    // The button sits inside the bar, which is itself the toggle - so the click
    // has to stop there.
    card({ args: { invoice_id: 7 }, result: "done" });
    await userEvent.click(bar());

    await userEvent.click(raw());

    expect(screen.getByText("Arguments")).toBeInTheDocument();
  });

  it("goes back to the formatted view", async () => {
    card({
      name: "get_current_datetime",
      args: { timezone: "UTC" },
      result: "Current date: 2026-07-31",
    });
    await userEvent.click(raw());
    expect(screen.getByText("Arguments")).toBeInTheDocument();

    await userEvent.click(raw());

    expect(screen.queryByText("Arguments")).toBeNull();
    expect(screen.getByText("2026-07-31")).toBeInTheDocument();
  });

  it("forgets the raw view when the card is closed", async () => {
    // Reopening on raw output would be a state nobody asked for twice.
    card({ result: "done" });
    await userEvent.click(raw());

    await userEvent.click(bar());
    await userEvent.click(bar());

    expect(screen.queryByText("Arguments")).toBeNull();
  });

  it("offers no raw view while the tool is still running", () => {
    // There is nothing raw to show yet, and the spinner takes the space.
    card({ status: "running", result: undefined });

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
    ];

    for (const [toolCall, expected] of cases) {
      const { unmount } = card(toolCall);
      await userEvent.click(bar());
      expect(screen.getByText(expected), expected).toBeInTheDocument();
      unmount();
    }
  });

  it("shows nothing for the skills listing, which the model reads and people do not", async () => {
    card({ name: "list_skills", result: JSON.stringify([{ name: "refunds" }]) });

    await userEvent.click(bar());

    expect(screen.queryByText(/refunds/)).toBeNull();
  });

  it("renders a structured result as JSON rather than as [object Object]", async () => {
    // A tool can return an object; the raw view and the generic view both have to
    // make text of it.
    card({ result: { id: 7 } as never });

    await userEvent.click(bar());

    expect(screen.getByText(/"id": 7/)).toBeInTheDocument();
  });

  it("shows an empty result as empty rather than as the word undefined", async () => {
    card({ result: undefined });

    await userEvent.click(bar());

    expect(screen.queryByText("undefined")).toBeNull();
  });

  it("keeps a fetched page's own renderer even before the page arrives", () => {
    // `fetch_url` is recognised from its arguments rather than its result, so the
    // card can name it while it is still fetching.
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
    expect(within(bar()).getByText("Fetched page")).toBeInTheDocument();
  });
});
