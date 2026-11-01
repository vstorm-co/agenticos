import { describe, expect, it } from "vitest";

import {
  checkDraft,
  checksOf,
  contentOf,
  draftOf,
  EMPTY_DRAFT,
  expectsSomething,
  lengthFields,
  sameCheck,
} from "./case-form";

const CASE = {
  input: "How long is the return window?",
  history: [{ role: "user" as const, content: "I bought a kettle" }],
  reference_answer: "30 days",
  counter_example: null,
  expected_tool_calls: [
    { tool: "search", args: { q: "refund", limit: 5, exact: true, id: "42", tags: ["a"] } },
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
      {
        tool: "search",
        args: [
          { key: "q", value: "refund" },
          { key: "limit", value: "5" },
          { key: "exact", value: "true" },
          { key: "id", value: '"42"' },
          { key: "tags", value: '["a"]' },
        ],
      },
      { tool: "lookup_order", args: [] },
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
        { tool: " search ", args: [{ key: " ", value: "x" }] },
        { tool: "", args: [] },
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
      checks: [
        { type: "json_schema", value: "{", rest: {} },
        { type: "json_schema", value: "[1]", rest: {} },
        { type: "json_schema", value: "null", rest: {} },
        { type: "max_latency_ms", value: "soon", rest: {} },
        { type: "contains", value: " ", rest: {} },
      ],
    });
    expect(read.content).toBeNull();
    expect(read.problems).toEqual([
      { field: "checks", key: "schemaNotObject" },
      { field: "checks", key: "schemaNotObject" },
      { field: "checks", key: "schemaNotObject" },
      { field: "checks", key: "notNumber" },
      { field: "checks", key: "checkEmpty" },
    ]);
  });

  it("expects something once any one of the four says what the answer is tested against", () => {
    const only = { ...EMPTY_DRAFT, input: "q", note: "why", tags: "a" };
    expect(expectsSomething(only)).toBe(false);
    expect(expectsSomething({ ...only, expected_tool_calls: [{ tool: " ", args: [] }] })).toBe(
      false,
    );
    expect(expectsSomething({ ...only, reference_answer: "yes" })).toBe(true);
    expect(expectsSomething({ ...only, counter_example: "no" })).toBe(true);
    expect(expectsSomething({ ...only, expected_tool_calls: [{ tool: "search", args: [] }] })).toBe(
      true,
    );
    expect(expectsSomething({ ...only, checks: [{ type: "contains", value: "", rest: {} }] })).toBe(
      true,
    );
  });
});

describe("a length check", () => {
  it("reads back what it was made from, and leaves out a blank path", () => {
    const stored = { type: "length", unit: "words", min: 10, max: 50, path: "data.summary" };
    expect(checkDraft(stored)).toEqual({
      type: "length",
      value: "50",
      rest: { unit: "words", min: "10", path: "data.summary" },
    });
    expect(checksOf([checkDraft(stored)]).checks).toEqual([stored]);
    expect(checksOf([checkDraft({ type: "length", max: 80 })]).checks).toEqual([
      { type: "length", unit: "characters", min: null, max: 80 },
    ]);
  });

  it("counts characters until told otherwise, as a fresh draft", () => {
    expect(lengthFields({ type: "length", value: "", rest: {} })).toEqual({
      unit: "characters",
      min: "",
      path: "",
    });
  });

  it("needs a bound, whole numbers, and a least not above the most", () => {
    const draft = (min: string, max: string) => ({
      type: "length",
      value: max,
      rest: { unit: "words", min, path: " " },
    });
    expect(checksOf([draft("", " ")]).problems).toEqual(["checkEmpty"]);
    expect(checksOf([draft("1.5", "")]).problems).toEqual(["notNumber"]);
    expect(checksOf([draft("", "-3")]).problems).toEqual(["notNumber"]);
    expect(checksOf([draft("9", "3")]).problems).toEqual(["lengthRange"]);
    expect(checksOf([draft(" 3 ", "3")]).checks).toEqual([
      { type: "length", unit: "words", min: 3, max: 3 },
    ]);
  });
});

describe("sameCheck", () => {
  it("compares what a check checks, not the defaults the server filled in", () => {
    const pattern = checkDraft({ type: "regex", value: "^Hi" });
    expect(
      sameCheck(pattern, checkDraft({ type: "regex", value: "^Hi", case_sensitive: false })),
    ).toBe(true);
    expect(sameCheck(pattern, checkDraft({ type: "regex", value: "^Hello" }))).toBe(false);
    expect(sameCheck(pattern, checkDraft({ type: "contains", value: "^Hi" }))).toBe(false);
  });

  it("tells length checks apart by their unit, least and path", () => {
    const most = checkDraft({ type: "length", unit: "words", max: 50 });
    expect(sameCheck(most, checkDraft({ type: "length", unit: "words", min: null, max: 50 }))).toBe(
      true,
    );
    expect(sameCheck(most, checkDraft({ type: "length", max: 50 }))).toBe(false);
    expect(sameCheck(most, checkDraft({ type: "length", unit: "words", min: 1, max: 50 }))).toBe(
      false,
    );
    expect(sameCheck(most, checkDraft({ type: "length", unit: "words", max: 50, path: "a" }))).toBe(
      false,
    );
  });
});
