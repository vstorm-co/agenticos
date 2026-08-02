import { describe, expect, it } from "vitest";

import { collapseUnchanged, diffLines, diffStat, MAX_DIFF_LINES } from "./diff";

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
