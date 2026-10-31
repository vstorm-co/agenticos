import { DEFAULT_TABLE_DISPLAY } from "./table-display";
import { describe, expect, it } from "vitest";

import { formatCellValue, recordCellText } from "./format-cell-value";
import type { ColumnDef, RecordRead } from "@/types/tables";

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
  it("shows a rich-text body instead of its frontmatter in compact views", () => {
    const col = column({ type: "rich_text" });
    expect(formatCellValue(col, "---\ntitle: Hidden\n---\n# Body\n", boolLabel)).toBe("# Body");
    expect(formatCellValue(col, 5, boolLabel)).toBe("");
  });
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

  it("writes a date as the viewer's locale does, on the day it names", () => {
    expect(formatCellValue(column({ type: "date" }), "2026-10-04", boolLabel, "en-US")).toBe(
      "Oct 4, 2026",
    );
    expect(formatCellValue(column({ type: "date" }), "2026-10-04", boolLabel, "pl")).toBe(
      "4 paź 2026",
    );
    expect(
      formatCellValue(column({ type: "datetime" }), "2026-10-04T10:00:00Z", boolLabel, "en-US"),
    ).toMatch(/^Oct 4, 2026, \d{1,2}:\d{2}/);
    // Not a date after all: shown as it is stored.
    expect(formatCellValue(column({ type: "date" }), "soon", boolLabel, "en-US")).toBe("soon");
  });

  it("stringifies text, long_text, number and integer values", () => {
    expect(formatCellValue(column({ type: "text" }), "hello", boolLabel)).toBe("hello");
    expect(formatCellValue(column({ type: "long_text" }), "a long story", boolLabel)).toBe(
      "a long story",
    );
    expect(formatCellValue(column({ type: "number" }), 3.5, boolLabel)).toBe("3.5");
    expect(formatCellValue(column({ type: "integer" }), 7, boolLabel)).toBe("7");
  });

  it("draws a rating as stars out of five, and nothing for a value that is not one", () => {
    const col = column({ type: "rating" });
    expect(formatCellValue(col, 3, boolLabel)).toBe("★★★☆☆");
    expect(formatCellValue(col, "3", boolLabel)).toBe("");
  });

  it("joins what a lookup read, and counts a link it cannot name", () => {
    expect(formatCellValue(column({ type: "lookup" }), ["Atlas", 3] as never, boolLabel)).toBe(
      "Atlas, 3",
    );
    expect(formatCellValue(column({ type: "lookup" }), "one" as never, boolLabel)).toBe("one");
    expect(formatCellValue(column({ type: "link" }), ["r1", "r2"], boolLabel)).toBe("2");
    expect(formatCellValue(column({ type: "link" }), "r1", boolLabel)).toBe("");
  });
});

describe("a formula's answer", () => {
  it("reads a yes or no through the caller's labels, anything else as itself", () => {
    const col = column({ type: "formula" });
    expect(formatCellValue(col, false, boolLabel)).toBe("False");
    expect(formatCellValue(col, 12.5, boolLabel)).toBe("12.5");
  });
});

describe("recordCellText", () => {
  const record = {
    values: { c1: ["r1", "r2"], c2: 4 },
    links: {
      c1: [
        { id: "r1", label: "Atlas" },
        { id: "r2", label: "Quill" },
      ],
    },
  } as unknown as RecordRead;

  it("names a link by the records it points at, and reads anything else as its value", () => {
    expect(recordCellText(column({ id: "c1", type: "link" }), record, boolLabel)).toBe(
      "Atlas, Quill",
    );
    expect(recordCellText(column({ id: "c2", type: "integer" }), record, boolLabel)).toBe("4");
    expect(
      recordCellText(
        column({ id: "c3", type: "link" }),
        { ...record, links: undefined },
        boolLabel,
      ),
    ).toBe("");
  });
});

describe("view date and time formats", () => {
  it.each([
    ["iso", "2026-10-31"],
    ["day_first", "31.10.2026"],
    ["month_first", "10/31/2026"],
    ["long", "October 31, 2026"],
  ] as const)(
    "formats date-only values as %s without shifting their day",
    (date_format, expected) => {
      expect(
        formatCellValue(column({ type: "date" }), "2026-10-31", boolLabel, "en-US", {
          ...DEFAULT_TABLE_DISPLAY,
          date_format,
        }),
      ).toBe(expected);
    },
  );
  it("selects 24h, 12h or no time without changing the date-time source", () => {
    const col = column({ type: "datetime" });
    const value = "2026-10-31T16:05:00";
    const display = { ...DEFAULT_TABLE_DISPLAY, date_format: "iso" as const };
    expect(
      formatCellValue(col, value, boolLabel, "en-US", { ...display, time_format: "24h" }),
    ).toBe("2026-10-31 · 16:05");
    expect(
      formatCellValue(col, value, boolLabel, "en-US", { ...display, time_format: "12h" }),
    ).toMatch(/2026-10-31 · 4:05.*PM/);
    expect(
      formatCellValue(col, value, boolLabel, "en-US", { ...display, time_format: "hidden" }),
    ).toBe("2026-10-31");
    expect(formatCellValue(col, "invalid", boolLabel, "en-US", display)).toBe("invalid");
  });
});
