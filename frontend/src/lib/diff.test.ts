import { describe, expect, it } from "vitest";

import {
  collapseUnchanged,
  type DiffLine,
  diffLines,
  diffStat,
  diffWords,
  foldUnchanged,
  locatePassage,
  MAX_DIFF_LINES,
} from "./diff";

const text = (...lines: string[]) => lines.join("\n");

describe("diffLines", () => {
  it("marks nothing when nothing changed", () => {
    const lines = diffLines(text("a", "b"), text("a", "b"));

    expect(lines.every((line) => line.kind === "same")).toBe(true);
  });

  it("reports a replacement as the old line then the new one", () => {
    // The order is the whole readability of a diff: "this became that".
    const lines = diffLines(text("name: Support"), text("name: Support EU"));

    expect(lines.map((line) => [line.kind, line.text])).toEqual([
      ["removed", "name: Support"],
      ["added", "name: Support EU"],
    ]);
  });

  it("keeps the lines around an insertion rather than re-reporting them", () => {
    const lines = diffLines(text("a", "c"), text("a", "b", "c"));

    expect(lines.map((line) => line.kind)).toEqual(["same", "added", "same"]);
  });

  it("numbers each side against its own text", () => {
    // A removed line has no line number in the new file, and vice versa -
    // inventing one is how a diff points at the wrong place.
    const lines = diffLines(text("a", "gone", "b"), text("a", "b"));

    expect(lines).toEqual([
      { kind: "same", text: "a", before: 1, after: 1 },
      { kind: "removed", text: "gone", before: 2 },
      { kind: "same", text: "b", before: 3, after: 2 },
    ]);
  });

  it("handles one side being empty", () => {
    expect(diffLines("", text("a")).map((line) => line.kind)).toEqual(["removed", "added"]);
  });

  it("refuses a text too large to diff rather than locking the tab", () => {
    // The table is quadratic. A spec of thousands of lines is generated, and
    // the honest answer for one of those is to say so.
    const huge = Array.from({ length: MAX_DIFF_LINES + 1 }, (_, i) => `line ${i}`).join("\n");

    const lines = diffLines(huge, "small");

    expect(lines.map((line) => line.kind)).toEqual(["removed", "added"]);
  });
});

describe("diffStat", () => {
  it("counts each side of the change", () => {
    const lines = diffLines(text("a", "b", "c"), text("a", "x", "y", "c"));

    expect(diffStat(lines)).toEqual({ added: 2, removed: 1 });
  });
});

describe("collapseUnchanged", () => {
  it("keeps context either side of a change", () => {
    const before = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
    const after = before.replace("line 10", "line ten");

    const collapsed = collapseUnchanged(diffLines(before, after), 2);
    const gaps = collapsed.filter((entry) => entry.kind === "gap");

    expect(gaps).toHaveLength(2);
    // Two lines of context each side of the removed/added pair.
    expect(collapsed.filter((entry) => entry.kind === "same")).toHaveLength(4);
  });

  it("says how many lines a gap swallowed", () => {
    // Otherwise a gap is indistinguishable from the end of the file.
    const before = Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n");
    const after = before.replace("line 0", "changed");

    const [, , , gap] = collapseUnchanged(diffLines(before, after), 1);

    expect(gap).toEqual({ kind: "gap", hidden: 10 });
  });

  it("reports the tail of a file that was truncated, not just the overlap", () => {
    // The loop that walks both sides stops at the shorter one; everything left
    // over on the old side is a removal nobody would otherwise see.
    const removed = diffLines(text("a", "b", "c", "d"), text("a", "b"));

    expect(removed.filter((line) => line.kind === "removed")).toEqual([
      { kind: "removed", text: "c", before: 3 },
      { kind: "removed", text: "d", before: 4 },
    ]);
  });

  it("leaves a diff with no changes entirely collapsed", () => {
    const collapsed = collapseUnchanged(diffLines(text("a", "b"), text("a", "b")));

    expect(collapsed).toEqual([{ kind: "gap", hidden: 2 }]);
  });
});

describe("diffWords", () => {
  it("marks only the words that changed in a line, on each side", () => {
    const { before, after } = diffWords(
      "Answer outright and plainly.",
      "Answer outright, briefly and plainly.",
    );
    expect(before.every((part) => !part.changed)).toBe(true);
    expect(before.map((part) => part.text).join("")).toBe("Answer outright and plainly.");
    expect(after.map((part) => part.text).join("")).toBe("Answer outright, briefly and plainly.");
    expect(
      after
        .filter((part) => part.changed)
        .map((part) => part.text)
        .join("")
        .trim(),
    ).toMatch(/^,\s*briefly$/);
  });

  it("keeps words whole and marks removals and replacements", () => {
    const { before, after } = diffWords("Refunds take 90 days", "Refunds take 30 days");
    expect(before.filter((part) => part.changed)).toEqual([{ text: "90", changed: true }]);
    expect(after.filter((part) => part.changed)).toEqual([{ text: "30", changed: true }]);
    expect(diffWords("a b", "").before).toEqual([{ text: "a b", changed: true }]);
    expect(diffWords("", "a").after).toEqual([{ text: "a", changed: true }]);
  });

  it("gives up on word marks past the size it can compare", () => {
    const long = "x ".repeat(MAX_DIFF_LINES);
    expect(diffWords(long, "y")).toEqual({
      before: [{ text: long, changed: true }],
      after: [{ text: "y", changed: true }],
    });
  });
});

describe("foldUnchanged", () => {
  it("folds long unchanged stretches and keeps their lines", () => {
    const lines = diffLines(
      ["a", "b", "c", "d", "e", "f", "g", "h", "i"].join("\n"),
      ["a", "b", "c", "d", "E", "f", "g", "h", "i"].join("\n"),
    );
    const folded = foldUnchanged(lines, 1);
    expect(folded[0]).toEqual({ kind: "fold", lines: lines.slice(0, 3) });
    expect(folded.at(-1)).toEqual({ kind: "fold", lines: lines.slice(7) });
    expect(folded.slice(1, -1).map((line) => (line as DiffLine).text)).toEqual([
      "d",
      "e",
      "E",
      "f",
    ]);
  });
});

it("ends without a fold when the last line changed", () => {
  const folded = foldUnchanged(diffLines("a\nb", "a\nB"), 0);
  expect(folded.at(-1)).toMatchObject({ kind: "added", text: "B" });
});

describe("locatePassage", () => {
  const passage = (old_text: string, context_before = "", context_after = "") => ({
    old_text,
    context_before,
    context_after,
  });

  it("finds the one occurrence its surroundings match, or the only one there is", () => {
    expect(
      locatePassage("Be kind. Be brief. Be kind.", passage("Be kind.", "Be brief. ", "")),
    ).toBe(19);
    expect(locatePassage("Hello there", passage("there", "Hi "))).toBe(6);
    expect(locatePassage("Be kind. Be kind.", passage("Be kind.", "x", "y"))).toBeNull();
    expect(locatePassage("Nothing here", passage("missing"))).toBeNull();
    expect(locatePassage("Start", passage("Start"))).toBe(0);
  });

  it("places an insertion after its surroundings", () => {
    expect(locatePassage("Intro. Rules.", passage("", "Intro. ", "Rules."))).toBe(7);
    expect(locatePassage("Rules.", passage("", "", "Rules."))).toBe(0);
    expect(locatePassage("A.x A.x", passage("", "A.", "x"))).toBeNull();
  });
});
