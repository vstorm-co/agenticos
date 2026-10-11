import { describe, expect, it } from "vitest";

import { inferType, readCell, readCsvFile } from "./csv-cells";
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

describe("contacts and ratings", () => {
  it("reads an address, a link and a phone number as the service would store them", () => {
    expect(readCell(col("email"), " ada@example.com ")).toEqual({ value: "ada@example.com" });
    expect(readCell(col("email"), "ada")).toEqual({ problem: "email" });
    expect(readCell(col("url"), "https://a.co/x")).toEqual({ value: "https://a.co/x" });
    expect(readCell(col("url"), "a.co")).toEqual({ problem: "url" });
    expect(readCell(col("phone"), "+48 600 100 200")).toEqual({ value: "+48 600 100 200" });
    expect(readCell(col("phone"), "+1 23")).toEqual({ problem: "phone" });
    expect(readCell(col("phone"), "call me")).toEqual({ problem: "phone" });
  });

  it("reads a rating as a whole number from 1 to 5", () => {
    expect(readCell(col("rating"), "4")).toEqual({ value: 4 });
    expect(readCell(col("rating"), "4.5")).toEqual({ problem: "integer" });
    expect(readCell(col("rating"), "6")).toEqual({ problem: "rating" });
    expect(readCell(col("rating"), "0")).toEqual({ problem: "rating" });
  });

  it("types a column of addresses or links as one", () => {
    expect(inferType(["ada@example.com", "", "bob@example.org"])).toBe("email");
    expect(inferType(["https://a.co", "http://b.io/x"])).toBe("url");
  });
});

describe("inferType", () => {
  it("picks the narrowest type every value reads as, ignoring blanks", () => {
    expect(inferType(["3", "", "12"])).toBe("integer");
    expect(inferType(["0", "1"])).toBe("integer");
    expect(inferType(["3", "2,5"])).toBe("number");
    expect(inferType(["yes", "No", " "])).toBe("boolean");
    expect(inferType(["2026-09-30", "2026-10-01"])).toBe("date");
    expect(inferType(["2026-09-30T10:00:00Z", "2026-09-30 11:30"])).toBe("datetime");
  });

  it("falls back to text, long text for a line break or a long value, text when empty", () => {
    expect(inferType(["Acme", "3"])).toBe("text");
    // Parsable by `Date`, but not written as ISO: not a datetime.
    expect(inferType(["Sep 30 2026"])).toBe("text");
    expect(inferType(["one\ntwo"])).toBe("long_text");
    expect(inferType(["x".repeat(1001)])).toBe("long_text");
    expect(inferType(["", "  "])).toBe("text");
  });
});

describe("readCsvFile", () => {
  it("reads the header and the rows that hold anything, or null when none do", async () => {
    expect(await readCsvFile(new File(["A,B\n1,2\n,\n"], "f.csv"))).toEqual({
      headers: ["A", "B"],
      rows: [["1", "2"]],
    });
    expect(await readCsvFile(new File(["A,B\n"], "f.csv"))).toBeNull();
    expect(await readCsvFile(new File([""], "f.csv"))).toBeNull();
  });
});
