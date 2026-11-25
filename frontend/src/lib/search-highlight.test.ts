import { describe, expect, it } from "vitest";

import { highlightSegments } from "./search-highlight";

const marked = (text: string, query: string) =>
  highlightSegments(text, query)
    .filter((segment) => segment.match)
    .map((segment) => segment.text);

describe("highlightSegments", () => {
  it("marks the exact phrase as one span, ignoring case and spacing", () => {
    expect(marked("Refunds are issued within  30 days of purchase.", "within 30 DAYS")).toEqual([
      "within  30 days",
    ]);
  });

  it("falls back to the query's words when the phrase is not there", () => {
    expect(marked("Purchases can be refunded; refunds take days.", "refunds within days")).toEqual([
      "refunds",
      "days",
    ]);
  });

  it("ignores words too short to mean anything", () => {
    expect(marked("A list of items in a box", "a of in")).toEqual([]);
  });

  it("keeps the text whole and unmarked when nothing matches", () => {
    expect(highlightSegments("Nothing alike here", "refund policy")).toEqual([
      { text: "Nothing alike here", match: false },
    ]);
  });

  it("returns the text unmarked for an empty query or text", () => {
    expect(highlightSegments("Some text", "   ")).toEqual([{ text: "Some text", match: false }]);
    expect(highlightSegments("", "query")).toEqual([{ text: "", match: false }]);
  });

  it("treats the query as text, not a pattern", () => {
    expect(marked("Costs (net) are $5.", "(net)")).toEqual(["(net)"]);
  });

  it("matches words outside ASCII", () => {
    expect(marked("Zwroty są możliwe przez 30 dni.", "możliwe zwroty")).toEqual([
      "Zwroty",
      "możliwe",
    ]);
  });

  it("puts every character back in order", () => {
    const text = "Alpha beta gamma beta.";
    expect(
      highlightSegments(text, "beta")
        .map((segment) => segment.text)
        .join(""),
    ).toBe(text);
  });
});
