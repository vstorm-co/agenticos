import { describe, expect, it } from "vitest";

import { readTable, tableToHtml, tableToMarkdown } from "./table-copy";

describe("tableToMarkdown", () => {
  it("pads a ragged row to the widest one, so the table still parses", () => {
    expect(tableToMarkdown({ head: [["a", "b"]], body: [["1"], ["2", "3", "4"]] })).toBe(
      ["| a | b |  |", "| --- | --- | --- |", "| 1 |  |  |", "| 2 | 3 | 4 |"].join("\n"),
    );
  });

  it("gives a headless table an empty header, because GFM has no table without one", () => {
    expect(tableToMarkdown({ head: [], body: [["x"]] })).toBe("|  |\n| --- |\n| x |");
  });

  it("keeps a second header row as a row", () => {
    expect(tableToMarkdown({ head: [["a"], ["b"]], body: [] })).toBe("| a |\n| --- |\n| b |");
  });

  it("draws an empty table as one empty column rather than no table at all", () => {
    expect(tableToMarkdown({ head: [], body: [] })).toBe("|  |\n| --- |");
  });
});

describe("tableToHtml", () => {
  it("escapes what would otherwise be markup", () => {
    expect(tableToHtml({ head: [['"q"']], body: [["a & b"]] })).toBe(
      "<table><thead><tr><th>&quot;q&quot;</th></tr></thead>" +
        "<tbody><tr><td>a &amp; b</td></tr></tbody></table>",
    );
  });
});

describe("readTable", () => {
  it("reads every body and no header when there is none, whitespace collapsed", () => {
    const table = document.createElement("table");
    table.innerHTML = "<tbody><tr><td> a\n  b </td></tr></tbody><tbody><tr><td>c</td></tr></tbody>";

    expect(readTable(table)).toEqual({ head: [], body: [["a b"], ["c"]] });
  });
});
