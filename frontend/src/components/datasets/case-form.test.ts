import { describe, expect, it } from "vitest";

import { contentOf, draftOf, EMPTY_DRAFT } from "./case-form";

const CASE = {
  input: "How long is the return window?",
  history: [{ role: "user" as const, content: "I bought a kettle" }],
  reference_answer: "30 days",
  counter_example: null,
  expected_tool_calls: [{ tool: "search", args: { q: "refund" } }],
  tool_calls_ordered: true,
  checks: [],
  tags: ["returns", "billing"],
  note: null,
};

describe("the case draft", () => {
  it("reads back exactly what it was made from", () => {
    const read = contentOf(draftOf(CASE));
    expect(read.problems).toEqual([]);
    expect(read.content).toEqual(CASE);
  });

  it("keeps a counter-example and a note through the round trip", () => {
    const withBoth = { ...CASE, reference_answer: null, counter_example: "90 days", note: "why" };
    expect(contentOf(draftOf(withBoth)).content).toEqual(withBoth);
  });

  it("shows an empty structured field as an empty box, not []", () => {
    expect(draftOf(CASE).checks).toBe("");
    expect(draftOf(CASE).tags).toBe("returns, billing");
  });

  it("reads blank optional text as no value and trims the tags", () => {
    const read = contentOf({ ...EMPTY_DRAFT, input: "q", note: "  ", tags: " a, ,b " });
    expect(read.content).toMatchObject({ note: null, reference_answer: null, tags: ["a", "b"] });
  });

  it("names every structured field that is not a JSON list", () => {
    const read = contentOf({
      ...EMPTY_DRAFT,
      input: "q",
      history: "[{",
      expected_tool_calls: '{"tool": "search"}',
    });
    expect(read.content).toBeNull();
    expect(read.problems).toEqual([
      { field: "history", key: "notJson" },
      { field: "expected_tool_calls", key: "notList" },
    ]);
  });
});
