import { describe, expect, it } from "vitest";

import { inlinePieces, markdownLines, type MdLine } from "./markdown-tokens";

/** What the underlay draws, joined back - it must be the input, character for character. */
function joined(lines: MdLine[]): string {
  return lines.map((line) => line.pieces.map((piece) => piece.text).join("")).join("\n");
}

const styles = (text: string) => inlinePieces(text).map((piece) => [piece.style, piece.text]);

describe("inlinePieces", () => {
  it("keeps the markers as their own pieces around what they mark", () => {
    expect(styles("a **bold** and *soft* and `code` here")).toEqual([
      ["plain", "a "],
      ["marker", "**"],
      ["strong", "bold"],
      ["marker", "**"],
      ["plain", " and "],
      ["marker", "*"],
      ["emphasis", "soft"],
      ["marker", "*"],
      ["plain", " and "],
      ["marker", "`"],
      ["code", "code"],
      ["marker", "`"],
      ["plain", " here"],
    ]);
  });

  it("reads a link as its words and its address, and a variable as one token", () => {
    expect(styles("see [the docs](https://x.test) for {{user_name}}")).toEqual([
      ["plain", "see "],
      ["marker", "["],
      ["link", "the docs"],
      ["marker", "]("],
      ["url", "https://x.test"],
      ["marker", ")"],
      ["plain", " for "],
      ["variable", "{{user_name}}"],
    ]);
  });

  it("leaves snake_case names alone, and takes underscores at a word's edge", () => {
    expect(styles("call write_memory and edit_memory")).toEqual([
      ["plain", "call write_memory and edit_memory"],
    ]);
    expect(styles("__strong__ _soft_")).toEqual([
      ["marker", "__"],
      ["strong", "strong"],
      ["marker", "__"],
      ["plain", " "],
      ["marker", "_"],
      ["emphasis", "soft"],
      ["marker", "_"],
    ]);
  });

  it("is plain text where nothing is marked, and nothing for nothing", () => {
    expect(styles("2 * 3 * 4")).toEqual([["plain", "2 * 3 * 4"]]);
    expect(inlinePieces("")).toEqual([]);
  });
});

describe("markdownLines", () => {
  const source = [
    "# Title with `code`",
    "",
    "Some **text** here.",
    "- a list item",
    "1. a numbered one",
    "> a quote",
    "---",
    "| A | B |",
    "|---|:-:|",
    "```ts",
    "const x = 1; // **not bold**",
    "```",
    "#nope",
    "####### seven",
  ].join("\n");

  it("gives back every character of the source, in order", () => {
    expect(joined(markdownLines(source))).toBe(source);
  });

  it("says what each line is", () => {
    const lines = markdownLines(source);
    expect(lines.map((line) => line.kind)).toEqual([
      "heading",
      "text",
      "text",
      "list",
      "list",
      "quote",
      "rule",
      "table",
      "table",
      "fence",
      "code",
      "fence",
      "text",
      "text",
    ]);
    expect(lines[0]!.level).toBe(1);
  });

  it("dims a heading's hashes, a list's bullet and a quote's bar", () => {
    const [heading, , , list, , quote] = markdownLines(source);
    expect(heading!.pieces[0]).toEqual({ text: "#", style: "marker" });
    expect(heading!.pieces[1]).toEqual({ text: " Title with ", style: "strong" });
    expect(list!.pieces[0]).toEqual({ text: "- ", style: "marker" });
    expect(quote!.pieces).toEqual([
      { text: "> ", style: "marker" },
      { text: "a quote", style: "emphasis" },
    ]);
  });

  it("reads nothing inside a fence, and dims a table's pipes and its rule", () => {
    const lines = markdownLines(source);
    expect(lines[10]!.pieces).toEqual([{ text: "const x = 1; // **not bold**", style: "plain" }]);
    expect(lines[8]!.pieces.every((piece) => piece.style === "marker")).toBe(true);
    expect(lines[7]!.pieces.map((piece) => piece.style)).toContain("plain");
  });

  it("takes an empty heading as a heading", () => {
    expect(markdownLines("##")[0]).toEqual({
      kind: "heading",
      level: 2,
      pieces: [{ text: "##", style: "marker" }],
    });
  });
});
