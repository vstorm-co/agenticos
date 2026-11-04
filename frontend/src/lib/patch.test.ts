import { describe, expect, it } from "vitest";

import { capHunks, hunksOf } from "./patch";

describe("hunksOf", () => {
  it("drops the header and reads each hunk's lines by their mark", () => {
    const patch =
      "diff --git a/app.py b/app.py\nindex 1..2 100644\n--- a/app.py\n+++ b/app.py\n" +
      "@@ -1,3 +1,3 @@ def total\n a\n-b\n+B\n\\ No newline at end of file\n" +
      "@@ -10 +10 @@\n-x\n+y\n";

    expect(hunksOf(patch)).toEqual([
      {
        header: "@@ -1,3 +1,3 @@ def total",
        lines: [
          { kind: "context", text: "a" },
          { kind: "removed", text: "b" },
          { kind: "added", text: "B" },
          { kind: "note", text: " No newline at end of file" },
        ],
      },
      {
        header: "@@ -10 +10 @@",
        lines: [
          { kind: "removed", text: "x" },
          { kind: "added", text: "y" },
        ],
      },
    ]);
  });

  it("has no hunks for a binary file or a rename with nothing else changed", () => {
    expect(
      hunksOf("diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n"),
    ).toEqual([]);
    expect(hunksOf("")).toEqual([]);
  });

  it("reads a patch whose last line has no newline after it", () => {
    expect(hunksOf("@@ -1 +1 @@\n-a\n+b")[0]?.lines).toEqual([
      { kind: "removed", text: "a" },
      { kind: "added", text: "b" },
    ]);
  });

  it("keeps an empty context line, which git writes as a lone space", () => {
    expect(hunksOf("@@ -1,2 +1,2 @@\n \n-a\n")[0]?.lines).toEqual([
      { kind: "context", text: "" },
      { kind: "removed", text: "a" },
    ]);
  });
});

describe("capHunks", () => {
  const hunk = (header: string, count: number) => ({
    header,
    lines: Array.from({ length: count }, (_, index) => ({
      kind: "added" as const,
      text: `${index}`,
    })),
  });

  it("keeps whole hunks under the limit and counts what it leaves out", () => {
    const { hunks, hidden } = capHunks([hunk("@@ a", 3), hunk("@@ b", 4), hunk("@@ c", 5)], 5);

    expect(hunks.map((kept) => [kept.header, kept.lines.length])).toEqual([
      ["@@ a", 3],
      ["@@ b", 2],
    ]);
    expect(hidden).toBe(7);
  });

  it("leaves a short diff as it is", () => {
    expect(capHunks([hunk("@@ a", 2)])).toEqual({ hunks: [hunk("@@ a", 2)], hidden: 0 });
  });
});
