import { describe, expect, it } from "vitest";

import { formatCellValue } from "./format-cell-value";
import type { ColumnDef } from "@/types/tables";

const boolLabel = (value: boolean) => (value ? "True" : "False");

function column(overrides: Partial<ColumnDef>): ColumnDef {
  return {
    id: "c1",
    label: "Column",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
    ...overrides,
  };
}

describe("formatCellValue", () => {
  it("renders nothing for null or undefined", () => {
    const col = column({ type: "text" });
    expect(formatCellValue(col, null, boolLabel)).toBe("");
    expect(formatCellValue(col, undefined as never, boolLabel)).toBe("");
  });

  it("renders a boolean through the caller's own labels", () => {
    const col = column({ type: "boolean" });
    expect(formatCellValue(col, true, boolLabel)).toBe("True");
    expect(formatCellValue(col, false, boolLabel)).toBe("False");
  });

  it("renders nothing for a non-boolean value on a boolean column", () => {
    const col = column({ type: "boolean" });
    expect(formatCellValue(col, "not-a-bool", boolLabel)).toBe("");
  });

  it("resolves a single_select value to its option's label", () => {
    const col = column({
      type: "single_select",
      options: [
        { id: "o1", label: "Open", archived: false },
        { id: "o2", label: "Closed", archived: true },
      ],
    });
    expect(formatCellValue(col, "o1", boolLabel)).toBe("Open");
    // Archived options still resolve - a record holding one still shows its label.
    expect(formatCellValue(col, "o2", boolLabel)).toBe("Closed");
  });

  it("renders nothing for a single_select value naming no option", () => {
    const col = column({ type: "single_select", options: [] });
    expect(formatCellValue(col, "missing", boolLabel)).toBe("");
  });

  it("joins multi_select labels with a comma", () => {
    const col = column({
      type: "multi_select",
      options: [
        { id: "o1", label: "Rush", archived: false },
        { id: "o2", label: "Gift", archived: false },
      ],
    });
    expect(formatCellValue(col, ["o1", "o2"], boolLabel)).toBe("Rush, Gift");
  });

  it("drops a multi_select id naming no option and handles a non-array value", () => {
    const col = column({
      type: "multi_select",
      options: [{ id: "o1", label: "Rush", archived: false }],
    });
    expect(formatCellValue(col, ["o1", "missing"], boolLabel)).toBe("Rush");
    expect(formatCellValue(col, "not-an-array", boolLabel)).toBe("");
  });

  it("renders a date/datetime value as its raw stored string", () => {
    expect(formatCellValue(column({ type: "date" }), "2026-09-23", boolLabel)).toBe("2026-09-23");
    expect(formatCellValue(column({ type: "date" }), 5, boolLabel)).toBe("");
    expect(formatCellValue(column({ type: "datetime" }), "2026-09-23T10:00:00Z", boolLabel)).toBe(
      "2026-09-23T10:00:00Z",
    );
  });

  it("stringifies text, long_text, number and integer values", () => {
    expect(formatCellValue(column({ type: "text" }), "hello", boolLabel)).toBe("hello");
    expect(formatCellValue(column({ type: "long_text" }), "a long story", boolLabel)).toBe(
      "a long story",
    );
    expect(formatCellValue(column({ type: "number" }), 3.5, boolLabel)).toBe("3.5");
    expect(formatCellValue(column({ type: "integer" }), 7, boolLabel)).toBe("7");
  });
});
