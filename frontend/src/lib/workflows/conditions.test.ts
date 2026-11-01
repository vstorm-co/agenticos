import { describe, expect, it } from "vitest";

import {
  type Condition,
  type ConditionRow,
  compileCondition,
  isComplete,
  parseCondition,
  takesNoValue,
} from "./conditions";

const row = (field: string, op: ConditionRow["op"], value = ""): ConditionRow => ({
  field,
  op,
  value,
});
const all = (...rows: ConditionRow[]): Condition => ({ rows, join: "and" });

describe("compileCondition", () => {
  it.each([
    [row("score", "gte", "50"), "item.score >= `50`"],
    [row("score", "gt", "-1.5"), "item.score > `-1.5`"],
    [row("active", "eq", "true"), "item.active == `true`"],
    [row("name", "eq", "Ada"), "item.name == 'Ada'"],
    [row("name", "ne", "O'Brien"), "item.name != 'O\\'Brien'"],
    [row("path", "lt", "a\\b"), "item.path < 'a\\\\b'"],
    [row("n", "lte", " 3 "), "item.n <= `3`"],
    [row("tags", "contains", "vip"), "contains(item.tags || '', 'vip')"],
    [row("email", "startsWith", "ada"), "starts_with(to_string(item.email || ''), 'ada')"],
    [row("email", "endsWith", ".pl"), "ends_with(to_string(item.email || ''), '.pl')"],
    [row("owner", "notEmpty"), "item.owner"],
    [row("owner", "empty"), "!item.owner"],
    [row("address.city", "eq", "Łódź"), "item.address.city == 'Łódź'"],
    [row("first name", "eq", "Ada"), "item.\"first name\" == 'Ada'"],
    [row("", "eq", "Ada"), "item == 'Ada'"],
  ])("writes %o", (clause, expression) => {
    expect(compileCondition(all(clause), "item")).toBe(expression);
  });

  it("joins rows, leaves out one not finished, and writes nothing for none", () => {
    expect(
      compileCondition(
        { rows: [row("a", "eq", "1"), row("b", "eq", ""), row("c", "empty")], join: "or" },
        "value",
      ),
    ).toBe("value.a == `1` || !value.c");
    expect(compileCondition(all(row("a", "eq", " ")), "item")).toBe("");
  });
});

describe("parseCondition", () => {
  it("reads back every expression it writes", () => {
    const conditions: Condition[] = [
      all(row("score", "gte", "50"), row("name", "contains", "a && b")),
      { rows: [row("x", "notEmpty"), row("y", "empty")], join: "or" },
      all(row("email", "startsWith", "it's")),
      all(row("email", "endsWith", ".pl")),
      all(row("first name", "ne", "Ada")),
      all(row("", "eq", "7")),
      all(row("flag", "eq", "false")),
    ];
    for (const condition of conditions) {
      expect(parseCondition(compileCondition(condition, "item"), "item")).toEqual(condition);
    }
  });

  it.each([
    ["item.score>50"],
    ["length(item.tags) > `2`"],
    ["item.a == `1` && item.b == `2` || item.c == `3`"],
    ['item.a == `"x"`'],
    ["value.a == `1`"],
    ["item.a == 'x' && "],
    // Read as rows, it would write back without the stray escape.
    ["item.a == 'x\\q'"],
  ])("reads %s as an expression it did not write", (expression) => {
    expect(parseCondition(expression, "item")).toBeNull();
  });

  it("ignores the space around an expression", () => {
    expect(parseCondition("  item.ok  ", "item")).toEqual(all(row("ok", "notEmpty")));
  });
});

describe("rows", () => {
  it("knows which checks take a value, and when a row is complete", () => {
    expect(takesNoValue("empty")).toBe(true);
    expect(takesNoValue("eq")).toBe(false);
    expect(isComplete(row("a", "empty"))).toBe(true);
    expect(isComplete(row("a", "eq", ""))).toBe(false);
  });
});
