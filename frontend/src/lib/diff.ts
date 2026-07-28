/**
 * A line diff, the shape a code review is read in.
 *
 * Written here rather than pulled in, because the whole of it is one classic
 * algorithm and a dependency would bring a parser, a renderer and a patch
 * format for the one function that gets used. Longest-common-subsequence over
 * lines: the same basis `diff -u` works from, so the output reads the way
 * anybody who has read a diff expects.
 */

export type DiffKind = "same" | "added" | "removed";

export interface DiffLine {
  kind: DiffKind;
  text: string;
  /** 1-based line number in the old text, absent for an added line. */
  before?: number;
  /** 1-based line number in the new text, absent for a removed line. */
  after?: number;
}

/**
 * Beyond this the table is longer than anybody reads and the O(n·m) table is
 * megabytes. Two agent specs are tens of lines; a spec that is thousands is a
 * generated file, and the honest answer for one of those is to say so.
 */
export const MAX_DIFF_LINES = 2000;

/**
 * Every line of both texts, marked as kept, added or removed.
 *
 * Unchanged lines are included rather than dropped: the caller decides how much
 * context to show, and a differ that has already thrown the context away cannot
 * be asked for more of it.
 */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");

  // The table is (n+1)×(m+1) numbers. Refusing is better than locking the tab.
  if (a.length > MAX_DIFF_LINES || b.length > MAX_DIFF_LINES) {
    return [
      { kind: "removed", text: before, before: 1 },
      { kind: "added", text: after, after: 1 },
    ];
  }

  // lengths[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const lengths: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i]![j] =
        a[i] === b[j]
          ? lengths[i + 1]![j + 1]! + 1
          : Math.max(lengths[i + 1]![j]!, lengths[i]![j + 1]!);
    }
  }

  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      lines.push({ kind: "same", text: a[i]!, before: i + 1, after: j + 1 });
      i++;
      j++;
    } else if (lengths[i + 1]![j]! >= lengths[i]![j + 1]!) {
      // Removals before additions on a changed line, so a replacement reads as
      // "this became that" rather than the other way round.
      lines.push({ kind: "removed", text: a[i]!, before: i + 1 });
      i++;
    } else {
      lines.push({ kind: "added", text: b[j]!, after: j + 1 });
      j++;
    }
  }
  while (i < a.length) lines.push({ kind: "removed", text: a[i]!, before: ++i });
  while (j < b.length) lines.push({ kind: "added", text: b[j]!, after: ++j });

  return lines;
}

/** How many lines each side changed by - what a summary line reports. */
export function diffStat(lines: DiffLine[]): { added: number; removed: number } {
  return {
    added: lines.filter((line) => line.kind === "added").length,
    removed: lines.filter((line) => line.kind === "removed").length,
  };
}

/**
 * The diff with long unchanged stretches replaced by gaps.
 *
 * `context` lines are kept either side of every change, which is what makes a
 * spec of a hundred lines with one edited word readable. A gap carries how many
 * lines it swallowed so nobody mistakes it for the end of the file.
 */
export function collapseUnchanged(
  lines: DiffLine[],
  context = 3,
): (DiffLine | { kind: "gap"; hidden: number })[] {
  const interesting = new Set<number>();
  lines.forEach((line, index) => {
    if (line.kind === "same") return;
    for (let at = index - context; at <= index + context; at++) {
      if (at >= 0 && at < lines.length) interesting.add(at);
    }
  });

  const out: (DiffLine | { kind: "gap"; hidden: number })[] = [];
  let hidden = 0;
  lines.forEach((line, index) => {
    if (interesting.has(index)) {
      if (hidden > 0) {
        out.push({ kind: "gap", hidden });
        hidden = 0;
      }
      out.push(line);
    } else {
      hidden++;
    }
  });
  if (hidden > 0) out.push({ kind: "gap", hidden });
  return out;
}
