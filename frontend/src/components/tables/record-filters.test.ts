import { describe, expect, it } from "vitest";

import { choiceOf, choicesFor, isComplete, newFilter, withChoice } from "./record-filters";
import type { ColumnDef, ColumnTypeName } from "@/types/tables";

const col = (type: ColumnTypeName): ColumnDef => ({
  id: "c1",
  label: "C",
  type,
  nullable: true,
  default: null,
  options: [],
  archived: false,
});

describe("record filters", () => {
  it("offers each type the operators the service accepts for it", () => {
    expect(choicesFor(col("text"))).toContain("starts_with");
    expect(choicesFor(col("integer"))).toContain("gte");
    expect(choicesFor(col("boolean"))).toEqual(["eq", "empty", "not_empty"]);
    expect(choicesFor(col("single_select"))).toContain("in");
    expect(choicesFor(col("multi_select"))).toEqual(["contains", "empty", "not_empty"]);
  });

  it("reads is_null as is empty or is not empty", () => {
    expect(choiceOf({ column_id: "c1", op: "is_null", value: true })).toBe("empty");
    expect(choiceOf({ column_id: "c1", op: "is_null", value: false })).toBe("not_empty");
    expect(choiceOf({ column_id: "c1", op: "gt", value: 1 })).toBe("gt");
  });

  it("starts a row on the type's first operator, a yes/no already at yes", () => {
    expect(newFilter(col("text"))).toEqual({ column_id: "c1", op: "contains", value: null });
    expect(newFilter(col("boolean"))).toEqual({ column_id: "c1", op: "eq", value: true });
  });

  it("keeps an operand that still fits the new operator and clears one that does not", () => {
    const number = col("integer");
    expect(withChoice({ column_id: "c1", op: "eq", value: 3 }, number, "gt")).toEqual({
      column_id: "c1",
      op: "gt",
      value: 3,
    });
    const select = col("single_select");
    expect(withChoice({ column_id: "c1", op: "eq", value: "o1" }, select, "in").value).toBeNull();
    expect(withChoice({ column_id: "c1", op: "in", value: ["o1"] }, select, "in").value).toEqual([
      "o1",
    ]);
    expect(withChoice({ column_id: "c1", op: "is_null", value: true }, number, "eq").value).toBe(
      null,
    );
    expect(withChoice({ column_id: "c1", op: "eq" }, number, "lt").value).toBeNull();
    expect(withChoice({ column_id: "c1", op: "eq", value: 3 }, number, "not_empty")).toEqual({
      column_id: "c1",
      op: "is_null",
      value: false,
    });
  });

  it("sends only a condition that says enough", () => {
    expect(isComplete({ column_id: "c1", op: "is_null", value: true })).toBe(true);
    expect(isComplete({ column_id: "c1", op: "is_null" })).toBe(false);
    expect(isComplete({ column_id: "c1", op: "in", value: [] })).toBe(false);
    expect(isComplete({ column_id: "c1", op: "in", value: ["o1"] })).toBe(true);
    expect(isComplete({ column_id: "c1", op: "eq", value: "" })).toBe(false);
    expect(isComplete({ column_id: "c1", op: "eq", value: null })).toBe(false);
    expect(isComplete({ column_id: "c1", op: "eq", value: false })).toBe(true);
  });
});
