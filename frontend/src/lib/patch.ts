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

/** How many lines one file's diff draws; the rest is counted and left to Copy patch. */
export const MAX_PATCH_LINES = 400;

/**
 * The hunks up to `MAX_PATCH_LINES` lines, and how many lines were left out.
 *
 * A task that rewrote a generated file can carry thousands of lines, and every
 * one of them a table row: the panel draws the start of it and says how much more
 * there is, which the copied patch still holds whole.
 */
export function capHunks(
  hunks: Hunk[],
  limit = MAX_PATCH_LINES,
): { hunks: Hunk[]; hidden: number } {
  const shown: Hunk[] = [];
  let left = limit;
  let hidden = 0;
  for (const hunk of hunks) {
    if (left <= 0) {
      hidden += hunk.lines.length;
      continue;
    }
    shown.push({ header: hunk.header, lines: hunk.lines.slice(0, left) });
    hidden += Math.max(hunk.lines.length - left, 0);
    left -= hunk.lines.length;
  }
  return { hunks: shown, hidden };
}

/** How many lines one task's diffs draw between them, across all its files. */
export const MAX_CHANGE_SET_LINES = 2000;

/**
 * Each file with its capped hunks, out of one budget for the whole change set.
 *
 * `capHunks` bounds a file, but a patch near its ceiling can be spread over
 * hundreds of files, each under that bound: a file drawn after the budget is
 * spent shows no lines and counts them all.
 */
export function capChangeSet<File extends { patch: string | null }>(
  files: File[],
  perFile = MAX_PATCH_LINES,
  total = MAX_CHANGE_SET_LINES,
): { file: File; hunks: Hunk[]; hidden: number }[] {
  let left = total;
  return files.map((file) => {
    const capped = capHunks(
      file.patch === null ? [] : hunksOf(file.patch),
      Math.min(perFile, left),
    );
    left -= capped.hunks.reduce((drawn, hunk) => drawn + hunk.lines.length, 0);
    return { file, ...capped };
  });
}
