import { describe, expect, it } from "vitest";

import { readCell } from "./csv-cells";
import type { ColumnDef, ColumnTypeName } from "@/types/tables";

const col = (type: ColumnTypeName): ColumnDef => ({
  id: "c1",
  label: "C",
  type,
  nullable: true,
  default: null,
  options: [
    { id: "o1", label: "Rush", archived: false },
    { id: "o2", label: "Gift", archived: false },
    { id: "o3", label: "Old", archived: true },
  ],
  archived: false,
});

describe("readCell", () => {
  it("reads an empty cell as no value, whatever the column", () => {
    expect(readCell(col("integer"), "  ")).toEqual({ value: null });
  });

  it("keeps text as it was, less the quote an export put before a formula", () => {
    expect(readCell(col("text"), " Acme ")).toEqual({ value: " Acme " });
    expect(readCell(col("long_text"), "'=SUM(1)")).toEqual({ value: "=SUM(1)" });
  });

  it("reads numbers with a decimal point or comma, and refuses a fraction for an integer", () => {
    expect(readCell(col("number"), "10,5")).toEqual({ value: 10.5 });
    expect(readCell(col("integer"), "3")).toEqual({ value: 3 });
    expect(readCell(col("integer"), "3.5")).toEqual({ problem: "integer" });
    expect(readCell(col("number"), "three")).toEqual({ problem: "number" });
  });

  it("reads a yes/no in the words an export and a person use", () => {
    expect(readCell(col("boolean"), "TRUE")).toEqual({ value: true });
    expect(readCell(col("boolean"), "no")).toEqual({ value: false });
    expect(readCell(col("boolean"), "maybe")).toEqual({ problem: "boolean" });
  });

  it("reads a date as YYYY-MM-DD and a date and time as an instant", () => {
    expect(readCell(col("date"), "2026-01-31")).toEqual({ value: "2026-01-31" });
    expect(readCell(col("date"), "31/01/2026")).toEqual({ problem: "date" });
    expect(readCell(col("datetime"), "2026-01-31T10:00:00Z")).toEqual({
      value: "2026-01-31T10:00:00.000Z",
    });
    expect(readCell(col("datetime"), "soon")).toEqual({ problem: "datetime" });
  });

  it("names a live option by label or id, several separated by semicolons", () => {
    expect(readCell(col("single_select"), "rush")).toEqual({ value: "o1" });
    expect(readCell(col("single_select"), "o2")).toEqual({ value: "o2" });
    expect(readCell(col("single_select"), "Old")).toEqual({ problem: "option" });
    expect(readCell(col("multi_select"), "Rush; gift;")).toEqual({ value: ["o1", "o2"] });
    expect(readCell(col("multi_select"), "Rush; Nope")).toEqual({ problem: "option" });
  });
});
