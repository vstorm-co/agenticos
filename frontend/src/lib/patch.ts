/**
 * One file's section of a unified diff, read into the hunks a diff viewer draws.
 *
 * Only what `git diff` writes is read: the header lines before the first `@@` are
 * dropped (the viewer names the file itself), each `@@` line opens a hunk, and every
 * line after it is context, an addition, a removal or a `\` note such as
 * "No newline at end of file".
 */

export type PatchLineKind = "context" | "added" | "removed" | "note";

export interface PatchLine {
  kind: PatchLineKind;
  text: string;
}

export interface Hunk {
  /** The `@@ -a,b +c,d @@` line, with whatever function name git put after it. */
  header: string;
  lines: PatchLine[];
}

const KIND: Record<string, PatchLineKind> = { "+": "added", "-": "removed", "\\": "note" };

export function hunksOf(patch: string): Hunk[] {
  const hunks: Hunk[] = [];
  const lines = patch.split("\n");
  // A patch ends in a newline, which leaves an empty last element that is no line.
  if (lines[lines.length - 1] === "") lines.pop();
  for (const line of lines) {
    if (line.startsWith("@@")) {
      hunks.push({ header: line, lines: [] });
      continue;
    }
    const hunk = hunks[hunks.length - 1];
    if (hunk === undefined) continue;
    hunk.lines.push({ kind: KIND[line.charAt(0)] ?? "context", text: line.slice(1) });
  }
  return hunks;
}
