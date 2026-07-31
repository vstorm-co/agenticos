import { describe, expect, it } from "vitest";

import { extractSources } from "./chat-sources";
import type { ChatMessage, ToolCall } from "@/types";

function toolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "tc-1",
    name: "search_documents",
    args: {},
    result: "",
    status: "completed",
    ...overrides,
  };
}

function message(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m-1",
    role: "assistant",
    content: "Here is what I found.",
    timestamp: new Date("2026-07-31T12:00:00Z"),
    ...overrides,
  };
}

/** What the knowledge tool actually writes back, verbatim in shape. */
const RAG_RESULT = [
  "[1] Source: handbook.pdf, page 4, chunk 2 [handbook] (score: 0.812)",
  "Refunds are granted within thirty days.",
  "[2] Source: policy.md (score: 0.640)",
  "Gift cards are excluded.",
].join("\n");

const WEB_RESULT = JSON.stringify({
  kind: "web_search",
  query: "refund law",
  results: [
    { title: "Consumer rights", url: "https://www.gov.example/rights", content: "Fourteen days." },
    { title: "", url: "https://acme.example/help", content: "Our own policy." },
  ],
});

/**
 * The citation list under an answer.
 *
 * It is derived rather than stored: the backend records a tool call and its raw
 * text, and this is what turns that into things somebody can click. Two rules
 * are load-bearing - a source with no readable result is skipped rather than
 * rendered as an empty card, and the parts timeline wins over the flat
 * `toolCalls` array, because a replayed conversation has both and only the parts
 * are ordered.
 */
describe("extractSources", () => {
  it("reads the knowledge tool's own result format", () => {
    const sources = extractSources(message({ toolCalls: [toolCall({ result: RAG_RESULT })] }));

    expect(sources).toHaveLength(2);
    expect(sources[0]).toMatchObject({
      index: 1,
      type: "rag",
      title: "handbook.pdf",
      subtitle: "p.4 · chunk 2",
      score: 0.812,
    });
  });

  it("leaves the subtitle off a passage with neither a page nor a chunk", () => {
    // A Markdown file has neither; " · " on its own reads as a missing value.
    const sources = extractSources(message({ toolCalls: [toolCall({ result: RAG_RESULT })] }));

    expect(sources[1]).toMatchObject({ title: "policy.md" });
    expect(sources[1]?.subtitle).toBeUndefined();
  });

  it("reads both knowledge tool names, because both exist", () => {
    for (const name of ["search_knowledge_base", "search_documents"]) {
      const sources = extractSources(
        message({ toolCalls: [toolCall({ name, result: RAG_RESULT })] }),
      );
      expect(sources, name).toHaveLength(2);
    }
  });

  it("reads web hits, naming each by its domain", () => {
    const sources = extractSources(
      message({ toolCalls: [toolCall({ name: "web_search", result: WEB_RESULT })] }),
    );

    expect(sources[0]).toMatchObject({
      index: 1,
      type: "web",
      title: "Consumer rights",
      subtitle: "gov.example",
      url: "https://www.gov.example/rights",
    });
  });

  it("falls back to the domain for a hit with no title", () => {
    const sources = extractSources(
      message({ toolCalls: [toolCall({ name: "search_web", result: WEB_RESULT })] }),
    );

    expect(sources[1]?.title).toBe("acme.example");
  });

  it("shows an unparsable URL as it arrived rather than dropping the hit", () => {
    // A provider occasionally returns a relative or malformed URL; the passage is
    // still worth citing, and `new URL` would otherwise throw inside the loop and
    // lose every source after it.
    const malformed = JSON.stringify({
      kind: "web_search",
      query: "refunds",
      results: [{ title: "", url: "acme.example/help", content: "text" }],
    });

    const sources = extractSources(
      message({ toolCalls: [toolCall({ name: "web_search", result: malformed })] }),
    );

    expect(sources[0]).toMatchObject({ title: "acme.example/help", subtitle: "acme.example/help" });
  });

  it("prefers the ordered timeline over the flat list, when a message has both", () => {
    // A replayed conversation carries both; only `parts` says what ran when.
    const sources = extractSources(
      message({
        parts: [
          { id: "p-1", type: "tool", toolCall: toolCall({ result: RAG_RESULT }) },
          { id: "p-2", type: "text", content: "Here is what I found." },
        ],
        toolCalls: [toolCall({ name: "web_search", result: WEB_RESULT })],
      }),
    );

    expect(sources.every((source) => source.type === "rag")).toBe(true);
  });

  it("skips a tool call that has no result yet", () => {
    // Which is every tool call while it is still running.
    expect(extractSources(message({ toolCalls: [toolCall({ result: undefined })] }))).toEqual([]);
  });

  it("skips a tool whose result is not text", () => {
    // A structured result belongs to a renderer, not to the citation list.
    expect(extractSources(message({ toolCalls: [toolCall({ result: { rows: 3 } })] }))).toEqual([]);
  });

  it("cites nothing for a tool that produces no sources", () => {
    expect(
      extractSources(message({ toolCalls: [toolCall({ name: "run_python", result: "42" })] })),
    ).toEqual([]);
  });

  it("cites nothing for a web result that is not the payload it claims to be", () => {
    // A provider error is returned as text on the same tool.
    expect(
      extractSources(
        message({ toolCalls: [toolCall({ name: "web_search", result: "upstream refused" })] }),
      ),
    ).toEqual([]);
  });

  it("cites nothing for a message that called no tools at all", () => {
    expect(extractSources(message())).toEqual([]);
  });
});
