import { describe, expect, it } from "vitest";

import { contentOf, draftOf, EMPTY_DRAFT, expectsSomething } from "./case-form";

const CASE = {
  input: "How long is the return window?",
  history: [{ role: "user" as const, content: "I bought a kettle" }],
  reference_answer: "30 days",
  counter_example: null,
  expected_tool_calls: [
    { tool: "search", args: { q: "refund" } },
    { tool: "lookup_order", args: {} },
  ],
  order_mode: "in_order" as const,
  checks: [
    { type: "contains", value: "30 days", case_sensitive: true },
    { type: "json_schema", schema: { type: "object" }, path: "data" },
    { type: "max_cost_usd", value: 0.05 },
    { type: "judge", criterion: "Polite" },
    { type: "from_the_future", knob: 3 },
  ],
  tags: ["returns", "billing"],
  note: null,
};

describe("the case draft", () => {
  it("reads back exactly what it was made from, unknown checks included", () => {
    const read = contentOf(draftOf(CASE));
    expect(read.problems).toEqual([]);
    expect(read.content).toEqual(CASE);
  });

  it("keeps a counter-example and a note through the round trip", () => {
    const withBoth = { ...CASE, reference_answer: null, counter_example: "90 days", note: "why" };
    expect(contentOf(draftOf(withBoth)).content).toEqual(withBoth);
  });

  it("writes each row the way the editor shows it", () => {
    const draft = draftOf(CASE);
    expect(draft.tags).toBe("returns, billing");
    expect(draft.expected_tool_calls).toEqual([
      { tool: "search", args: '{"q":"refund"}' },
      { tool: "lookup_order", args: "" },
    ]);
    expect(draft.checks.map((check) => [check.type, check.value])).toEqual([
      ["contains", "30 days"],
      ["json_schema", '{"type":"object"}'],
      ["max_cost_usd", "0.05"],
      ["judge", "Polite"],
      ["from_the_future", ""],
    ]);
  });

  it("reads a check missing its main parameter as an empty one", () => {
    const [check] = draftOf({ ...CASE, checks: [{ type: "regex" }] }).checks;
    expect(check).toEqual({ type: "regex", value: "", rest: {} });
  });

  it("reads blank optional text as no value, drops blank rows and trims the tags", () => {
    const read = contentOf({
      ...EMPTY_DRAFT,
      input: "q",
      note: "  ",
      tags: " a, ,b ",
      history: [{ role: "user", content: "  " }],
      expected_tool_calls: [
        { tool: " search ", args: " " },
        { tool: "", args: "{}" },
      ],
    });
    expect(read.content).toMatchObject({
      note: null,
      reference_answer: null,
      tags: ["a", "b"],
      history: [],
      expected_tool_calls: [{ tool: "search", args: {} }],
    });
  });

  it("names every row it cannot read, by field", () => {
    const read = contentOf({
      ...EMPTY_DRAFT,
      input: "q",
      expected_tool_calls: [{ tool: "search", args: "[1]" }],
      checks: [
        { type: "json_schema", value: "{", rest: {} },
        { type: "max_latency_ms", value: "soon", rest: {} },
        { type: "contains", value: " ", rest: {} },
      ],
    });
    expect(read.content).toBeNull();
    expect(read.problems).toEqual([
      { field: "expected_tool_calls", key: "argsNotObject" },
      { field: "checks", key: "schemaNotObject" },
      { field: "checks", key: "notNumber" },
      { field: "checks", key: "checkEmpty" },
    ]);
  });

  it("expects something once any one of the four says what the answer is tested against", () => {
    const only = { ...EMPTY_DRAFT, input: "q", note: "why", tags: "a" };
    expect(expectsSomething(only)).toBe(false);
    expect(expectsSomething({ ...only, expected_tool_calls: [{ tool: " ", args: "" }] })).toBe(
      false,
    );
    expect(expectsSomething({ ...only, reference_answer: "yes" })).toBe(true);
    expect(expectsSomething({ ...only, counter_example: "no" })).toBe(true);
    expect(expectsSomething({ ...only, expected_tool_calls: [{ tool: "search", args: "" }] })).toBe(
      true,
    );
    expect(expectsSomething({ ...only, checks: [{ type: "contains", value: "", rest: {} }] })).toBe(
      true,
    );
  });
});
