import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GenericToolResult, RawToolView } from "./generic";
import { RunPythonResult } from "./run-python";
import { LoadSkillResult, formatSkillName, parseLoadSkillResult } from "./skills";
import { RAGSearchResults, parseRAGResults } from "./rag";
import { WebSearchResults, parseWebSearch } from "./web-search";
import type { ToolCall } from "@/types";

// The Markdown renderer is loaded dynamically and highlights code; what these
// assert is what reaches it, not how it renders.
vi.mock("../markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

function toolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: "tc-1", name: "run_python", args: {}, status: "completed", ...overrides };
}

/**
 * What the chat shows for a tool that ran.
 *
 * Each of these replaces a wall of raw text with something readable, and each has
 * a state it must not misrepresent: a search that found nothing is not a failed
 * search, a tool still running is not a tool that returned nothing, and a result
 * this renderer cannot parse has to fall through to the raw view rather than
 * render as blank.
 */
describe("the knowledge search", () => {
  const RESULT = [
    "[1] Source: handbook.pdf, page 4, chunk 2 [handbook] (score: 0.812)",
    "Refunds are granted within thirty days.",
    "[2] Source: handbook.pdf, page 9 (score: 0.410)",
    "Gift cards are excluded.",
    "[3] Source: policy.md (score: 0.220)",
    "See the handbook.",
  ].join("\n");

  it("reads every field the tool writes", () => {
    const items = parseRAGResults(RESULT);

    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({
      index: 1,
      source: "handbook.pdf",
      page: "4",
      chunk: "2",
      collection: "handbook",
      score: "0.812",
      content: "Refunds are granted within thirty days.",
    });
  });

  it("reads a passage with no page, chunk or collection", () => {
    expect(parseRAGResults(RESULT)[2]).toMatchObject({
      source: "policy.md",
      page: undefined,
      chunk: undefined,
      collection: undefined,
    });
  });

  it("finds nothing in text that is not a result list", () => {
    expect(parseRAGResults("No relevant documents found.")).toEqual([]);
  });

  it("groups the chunks of one file into one card", () => {
    // Three chunks from the same PDF used to render as three identical cards.
    render(<RAGSearchResults result={RESULT} />);

    expect(screen.getByText("3 chunks")).toBeInTheDocument();
    expect(screen.getByText("2 sources")).toBeInTheDocument();
    expect(screen.getAllByTitle("handbook.pdf")).toHaveLength(1);
  });

  it("uses the singular for a single chunk from a single source", () => {
    render(<RAGSearchResults result={"[1] Source: a.md (score: 0.9)\nOne passage."} />);

    // Twice: the header counts them and the file's own row repeats its count.
    expect(screen.getAllByText("1 chunk")).toHaveLength(2);
    expect(screen.getByText("1 source")).toBeInTheDocument();
  });

  it("names the collection a file came from, when the tool said", () => {
    // Two collections can hold a file of the same name, and the answer depends on
    // which one was searched.
    render(<RAGSearchResults result={RESULT} />);

    expect(screen.getByTitle("Collection: handbook")).toBeInTheDocument();
  });

  it("expands a chunk to its full text, and collapses it again", () => {
    render(<RAGSearchResults result={RESULT} />);
    const chunk = screen.getByText("Refunds are granted within thirty days.");
    expect(chunk).toHaveClass("line-clamp-2");

    const [first] = screen.getAllByRole("button");
    return userEvent.click(first!).then(async () => {
      expect(screen.getByText("Refunds are granted within thirty days.")).not.toHaveClass(
        "line-clamp-2",
      );

      await userEvent.click(first!);
      expect(screen.getByText("Refunds are granted within thirty days.")).toHaveClass(
        "line-clamp-2",
      );
    });
  });

  it("opens one chunk at a time, so the panel does not grow without bound", async () => {
    render(<RAGSearchResults result={RESULT} />);
    const buttons = screen.getAllByRole("button");

    await userEvent.click(buttons[0]!);
    await userEvent.click(buttons[1]!);

    expect(screen.getByText("Refunds are granted within thirty days.")).toHaveClass("line-clamp-2");
    expect(screen.getByText("Gift cards are excluded.")).not.toHaveClass("line-clamp-2");
  });

  it("says where a passage came from inside its file", () => {
    render(<RAGSearchResults result={RESULT} />);

    expect(screen.getByText("p.4")).toBeInTheDocument();
    expect(screen.getByText("chunk 2")).toBeInTheDocument();
    // A passage with a page and no chunk says only the page.
    expect(screen.getByText("p.9")).toBeInTheDocument();
  });

  it("shows a chunk number with no page, for a file that has none", () => {
    render(<RAGSearchResults result={"[1] Source: a.md, chunk 7 (score: 0.5)\nBody."} />);

    expect(screen.getByText("chunk 7")).toBeInTheDocument();
  });

  it("scores each passage, and marks how relevant it is", () => {
    // The relevance dot is a quality signal rather than an alert, which is why
    // there is no red in it - but it still has to differ by band.
    const { container } = render(<RAGSearchResults result={RESULT} />);

    expect(screen.getByText("0.81")).toBeInTheDocument();
    expect(container.querySelector('[title="Relevance: 0.81"]')).toHaveClass("bg-foreground");
    expect(container.querySelector('[title="Relevance: 0.41"]')).toHaveClass("bg-foreground/55");
    expect(container.querySelector('[title="Relevance: 0.22"]')).toHaveClass("bg-foreground/25");
  });

  it("says a search that found nothing found nothing", () => {
    // Not the same as a failed search, and not the same as no search.
    render(<RAGSearchResults result="No relevant documents found for your query." />);

    expect(screen.getByText("No relevant documents found")).toBeInTheDocument();
  });

  it("renders nothing for a result it cannot read, so the raw view takes over", () => {
    const { container } = render(<RAGSearchResults result="something else entirely" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("survives a passage whose source the tool did not name", () => {
    render(<RAGSearchResults result={"[1] Source:  (score: 0.5)\nBody."} />);

    expect(screen.getByTitle("Unknown")).toBeInTheDocument();
  });
});

describe("the web search", () => {
  const PAYLOAD = JSON.stringify({
    kind: "web_search",
    query: "refund law",
    results: [
      {
        title: "Consumer rights",
        url: "https://www.gov.example/rights",
        content: "Fourteen days.",
        score: 0.92,
      },
      { title: "Acme help", url: "https://acme.example/help" },
    ],
  });

  it("reads the payload the tool writes", () => {
    const parsed = parseWebSearch(PAYLOAD);

    expect(parsed?.query).toBe("refund law");
    expect(parsed?.results).toHaveLength(2);
  });

  it("reads a payload with no query as one with an empty query", () => {
    const parsed = parseWebSearch(JSON.stringify({ kind: "web_search", results: [] }));

    expect(parsed).toEqual({ query: "", results: [] });
  });

  it("refuses anything that is not that payload", () => {
    // A provider error arrives as text on the same tool, and the raw renderer is
    // the right place for it.
    expect(parseWebSearch("upstream refused")).toBeNull();
    expect(parseWebSearch(JSON.stringify({ kind: "other", results: [] }))).toBeNull();
    expect(parseWebSearch(JSON.stringify({ kind: "web_search" }))).toBeNull();
    expect(parseWebSearch("null")).toBeNull();
  });

  it("lists each hit by title and domain", () => {
    render(<WebSearchResults data={parseWebSearch(PAYLOAD)!} />);

    expect(screen.getByText("2 web results")).toBeInTheDocument();
    expect(screen.getByText("Consumer rights")).toBeInTheDocument();
    expect(screen.getByText("gov.example")).toBeInTheDocument();
  });

  it("uses the singular for one hit", () => {
    const one = JSON.stringify({
      kind: "web_search",
      results: [{ title: "A", url: "https://a/" }],
    });

    render(<WebSearchResults data={parseWebSearch(one)!} />);

    expect(screen.getByText("1 web result")).toBeInTheDocument();
  });

  it("opens each hit in a tab that cannot reach back", () => {
    render(<WebSearchResults data={parseWebSearch(PAYLOAD)!} />);

    const link = screen.getByRole("link", { name: /Consumer rights/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows the domain as it stands when the URL cannot be parsed", () => {
    const malformed = JSON.stringify({
      kind: "web_search",
      results: [{ title: "A", url: "acme.example/help" }],
    });

    render(<WebSearchResults data={parseWebSearch(malformed)!} />);

    expect(screen.getByText("acme.example/help")).toBeInTheDocument();
  });

  it("clamps a snippet in the chat and shows it whole in the panel", () => {
    // The same component in two places: the transcript has one line to spare and
    // the deep-dive panel has the room.
    const { rerender } = render(<WebSearchResults data={parseWebSearch(PAYLOAD)!} />);
    expect(screen.getByText("Fourteen days.")).toHaveClass("line-clamp-2");

    rerender(<WebSearchResults data={parseWebSearch(PAYLOAD)!} detailed />);
    expect(screen.getByText("Fourteen days.")).toHaveClass("whitespace-pre-wrap");
  });

  it("shows the query and the relevance only in the deep-dive view", () => {
    const { rerender } = render(<WebSearchResults data={parseWebSearch(PAYLOAD)!} />);
    expect(screen.queryByText(/refund law/)).toBeNull();
    expect(screen.queryByText("92%")).toBeNull();

    rerender(<WebSearchResults data={parseWebSearch(PAYLOAD)!} detailed />);
    expect(screen.getByText(/refund law/)).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
  });

  it("says a search that found nothing found nothing", () => {
    render(<WebSearchResults data={{ query: "x", results: [] }} />);

    expect(screen.getByText("No web results found")).toBeInTheDocument();
  });
});

describe("running Python", () => {
  it("shows the code it ran, and its output", () => {
    render(
      <RunPythonResult
        toolCall={toolCall({ args: { code: "print(6*7)" } })}
        resultText={"stdout:\n42"}
      />,
    );

    expect(screen.getByTestId("markdown")).toHaveTextContent("```python");
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("shows the returned value beside what was printed", () => {
    render(<RunPythonResult toolCall={toolCall()} resultText={"stdout:\nworking\n\nresult: 42"} />);

    expect(screen.getByText(/working/)).toBeInTheDocument();
    expect(screen.getByText(/result: 42/)).toBeInTheDocument();
  });

  it("shows a returned value with nothing printed", () => {
    render(<RunPythonResult toolCall={toolCall()} resultText="result: 42" />);

    expect(screen.getByText("result: 42")).toBeInTheDocument();
  });

  it("shows an unrecognised result as output rather than dropping it", () => {
    render(<RunPythonResult toolCall={toolCall()} resultText="just some text" />);

    expect(screen.getByText("just some text")).toBeInTheDocument();
  });

  it("shows a failure as a failure", () => {
    render(
      <RunPythonResult
        toolCall={toolCall()}
        resultText="Execution failed: NameError: name 'x' is not defined"
      />,
    );

    expect(screen.getByText(/NameError/)).toBeInTheDocument();
  });

  it("says code is still running rather than showing an empty output box", () => {
    render(<RunPythonResult toolCall={toolCall({ status: "running" })} resultText="" />);

    expect(screen.getByText("Running…")).toBeInTheDocument();
  });

  it("says nothing about output for code that produced none", () => {
    // The tool's own words for it; an empty `<pre>` reads as a broken renderer.
    render(
      <RunPythonResult
        toolCall={toolCall({ args: { code: "x = 1" } })}
        resultText="(code ran successfully with no output)"
      />,
    );

    expect(screen.getByTestId("markdown")).toBeInTheDocument();
    expect(screen.queryByText("Output")).toBeNull();
  });

  it("shows a result with no code and no output as plain text", () => {
    // Reachable from a replayed conversation where the args were not stored.
    render(
      <RunPythonResult toolCall={toolCall()} resultText="(code ran successfully with no output)" />,
    );

    expect(screen.getByText("(code ran successfully with no output)")).toBeInTheDocument();
  });

  it("offers the output for copying, which is why it is one string", () => {
    render(<RunPythonResult toolCall={toolCall()} resultText={"stdout:\n42\n\nresult: 43"} />);

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });
});

describe("loading a skill", () => {
  it("shows the description and not the XML it arrived in", () => {
    render(
      <LoadSkillResult
        resultText={
          "<skill><name>refunds</name><description>How refunds work.</description></skill>"
        }
        status="completed"
      />,
    );

    expect(screen.getByText("How refunds work.")).toBeInTheDocument();
    expect(screen.queryByText(/<skill>/)).toBeNull();
  });

  it("reads a multi-line description", () => {
    expect(parseLoadSkillResult("<description>\n  Line one.\n  Line two.\n</description>")).toEqual(
      { description: "Line one.\n  Line two." },
    );
  });

  it("finds nothing in a result with no description", () => {
    expect(parseLoadSkillResult("<skill><name>refunds</name></skill>")).toBeNull();
    expect(parseLoadSkillResult("<description></description>")).toBeNull();
  });

  it("renders nothing when there is no description to show", () => {
    const { container } = render(<LoadSkillResult resultText="<skill/>" status="completed" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says it is loading, and says when it failed", () => {
    const { rerender } = render(<LoadSkillResult resultText="" status="running" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();

    rerender(<LoadSkillResult resultText="" status="error" />);
    expect(screen.getByText("Failed to load skill.")).toBeInTheDocument();
  });

  it("says it is loading for a result that arrived before the status did", () => {
    render(<LoadSkillResult resultText="<description>x</description>" status="running" />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("humanises a skill's stored name", () => {
    expect(formatSkillName("market_data")).toBe("Market Data");
    expect(formatSkillName("fire")).toBe("Fire");
    expect(formatSkillName("__odd__name")).toBe("Odd Name");
    expect(formatSkillName("")).toBe("");
  });
});

/**
 * The fallback for a tool nobody wrote a renderer for.
 *
 * It is the common path rather than the exceptional one: capabilities are a
 * registry, and a backend release can add a tool the day after this file was last
 * touched. So it has to make something readable out of anything - pretty JSON
 * where it can, wrapped text where it cannot - and never render blank.
 */
describe("a tool with no renderer of its own", () => {
  it("pretty-prints a JSON result", () => {
    render(
      <GenericToolResult
        toolCall={toolCall({ name: "post_invoice" })}
        resultText='{"id":7,"total":42}'
      />,
    );

    expect(screen.getByText(/"total": 42/)).toBeInTheDocument();
  });

  it("wraps a result that is not JSON rather than dropping it", () => {
    render(<GenericToolResult toolCall={toolCall()} resultText="Posted invoice 7." />);

    expect(screen.getByText("Posted invoice 7.")).toBeInTheDocument();
  });

  it("treats a bare JSON scalar as text, because pretty-printing it changes nothing", () => {
    render(<GenericToolResult toolCall={toolCall()} resultText="42" />);

    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("shows nothing for a call that carried no arguments at all", () => {
    // `args` arrives from the stream and is null for a no-argument tool.
    // Formatted as "null" it would read as an argument the model passed.
    render(
      <GenericToolResult
        toolCall={toolCall({ args: null as unknown as ToolCall["args"] })}
        resultText="ok"
      />,
    );

    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("shows the arguments it was called with", () => {
    render(<GenericToolResult toolCall={toolCall({ args: { invoice_id: 7 } })} resultText="ok" />);

    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText(/"invoice_id": 7/)).toBeInTheDocument();
  });

  it("says nothing about arguments for a tool that takes none", () => {
    // Three shapes mean "none": absent, an empty object, and the string `{}` a
    // raw stream frame carries.
    for (const args of [undefined, {}, "{}", "  "]) {
      const { unmount } = render(
        <GenericToolResult toolCall={toolCall({ args: args as never })} resultText="ok" />,
      );

      expect(screen.queryByText("Arguments")).toBeNull();
      unmount();
    }
  });

  it("reads arguments that arrived as a JSON string", () => {
    render(<GenericToolResult toolCall={toolCall({ args: '{"a":1}' as never })} resultText="ok" />);

    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
  });

  it("shows arguments that are a string and not JSON as they stand", () => {
    render(
      <GenericToolResult toolCall={toolCall({ args: "just text" as never })} resultText="ok" />,
    );

    expect(screen.getByText("just text")).toBeInTheDocument();
  });

  it("says it is running, and says when it failed", () => {
    const { rerender } = render(
      <GenericToolResult toolCall={toolCall({ status: "running" })} resultText="" />,
    );
    expect(screen.getByText("Running…")).toBeInTheDocument();

    rerender(<GenericToolResult toolCall={toolCall({ status: "error" })} resultText="" />);
    expect(screen.getByText("Tool failed.")).toBeInTheDocument();
  });

  it("shows a completed tool that returned nothing without claiming it is running", () => {
    render(<GenericToolResult toolCall={toolCall()} resultText="" />);

    expect(screen.queryByText("Running…")).toBeNull();
  });
});

describe("the raw view behind every tool", () => {
  it("shows the arguments and the exact output, both copyable", () => {
    // The escape hatch: whatever a renderer decided to show, this is what the
    // tool actually said.
    render(
      <RawToolView
        toolCall={toolCall({ args: { a: 1 }, result: "raw output" })}
        resultText="raw output"
      />,
    );

    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /copy/i })).toHaveLength(2);
  });

  it("says a tool took no arguments rather than showing an empty block", () => {
    render(<RawToolView toolCall={toolCall({ args: {} })} resultText="" />);

    expect(screen.getByText("No arguments")).toBeInTheDocument();
  });

  it("shows no result section for a tool that has not answered", () => {
    render(<RawToolView toolCall={toolCall({ args: { a: 1 } })} resultText="" />);

    expect(screen.queryByText("Result")).toBeNull();
  });

  it("shows no result section for an answer that was empty", () => {
    // `result` present and the text empty: a tool that returned `""`.
    render(<RawToolView toolCall={toolCall({ args: { a: 1 }, result: "" })} resultText="" />);

    expect(screen.queryByText("Result")).toBeNull();
  });

  it("treats a non-string, non-object argument as no arguments at all", () => {
    // Reachable from a malformed stream frame.
    render(<RawToolView toolCall={toolCall({ args: 7 as never })} resultText="" />);

    expect(screen.getByText("7")).toBeInTheDocument();
  });
});
