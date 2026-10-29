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

/** A run of words, and whether it differs from the other side. */
export interface WordPart {
  text: string;
  changed: boolean;
}

/** Words, the spaces between them and punctuation, so a highlight never splits a word. */
function tokens(text: string): string[] {
  return text.match(/\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu) ?? [];
}

function merged(parts: WordPart[]): WordPart[] {
  return parts.reduce<WordPart[]>((out, part) => {
    const last = out.at(-1);
    if (last && last.changed === part.changed) last.text += part.text;
    else out.push({ ...part });
    return out;
  }, []);
}

/**
 * Two versions of one line, each split into the words it shares with the other
 * and the words it does not - what makes a one-word change in a long line visible.
 */
export function diffWords(
  before: string,
  after: string,
): { before: WordPart[]; after: WordPart[] } {
  const a = tokens(before);
  const b = tokens(after);
  if (a.length > MAX_DIFF_LINES || b.length > MAX_DIFF_LINES) {
    return { before: [{ text: before, changed: true }], after: [{ text: after, changed: true }] };
  }
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
  const left: WordPart[] = [];
  const right: WordPart[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      left.push({ text: a[i]!, changed: false });
      right.push({ text: b[j]!, changed: false });
      i++;
      j++;
    } else if (lengths[i + 1]![j]! >= lengths[i]![j + 1]!) {
      left.push({ text: a[i++]!, changed: true });
    } else {
      right.push({ text: b[j++]!, changed: true });
    }
  }
  while (i < a.length) left.push({ text: a[i++]!, changed: true });
  while (j < b.length) right.push({ text: b[j++]!, changed: true });
  return { before: merged(left), after: merged(right) };
}

/** A folded stretch of unchanged lines, kept so it can be opened again. */
export interface FoldedLines {
  kind: "fold";
  lines: DiffLine[];
}

/**
 * The diff with long unchanged stretches folded away, `context` lines kept either
 * side of every change. Unlike `collapseUnchanged`, a fold keeps the lines it hid.
 */
export function foldUnchanged(lines: DiffLine[], context = 3): (DiffLine | FoldedLines)[] {
  const near = new Set<number>();
  lines.forEach((line, index) => {
    if (line.kind === "same") return;
    for (let at = Math.max(0, index - context); at <= index + context; at++) near.add(at);
  });
  const out: (DiffLine | FoldedLines)[] = [];
  let fold: DiffLine[] = [];
  lines.forEach((line, index) => {
    if (near.has(index)) {
      if (fold.length) out.push({ kind: "fold", lines: fold });
      fold = [];
      out.push(line);
    } else fold.push(line);
  });
  if (fold.length) out.push({ kind: "fold", lines: fold });
  return out;
}

/** A suggested passage and the text around it when it was proposed. */
export interface Passage {
  old_text: string;
  context_before: string;
  context_after: string;
}

/**
 * Where a suggested passage starts in `text`, found the way the server finds it:
 * the one occurrence its surroundings still match, or the only occurrence there is.
 * `null` when the text has moved on.
 */
export function locatePassage(text: string, passage: Passage): number | null {
  const surrounded = (position: number) => {
    const end = position + passage.old_text.length;
    const before = passage.context_before
      ? text.slice(0, position).endsWith(passage.context_before)
      : position === 0;
    const after = passage.context_after
      ? text.slice(end).startsWith(passage.context_after)
      : end === text.length;
    return before && after;
  };
  const occurrences = (needle: string) => {
    const found: number[] = [];
    for (let at = text.indexOf(needle); at !== -1; at = text.indexOf(needle, at + 1))
      found.push(at);
    return found;
  };
  if (passage.old_text) {
    const positions = occurrences(passage.old_text);
    const exact = positions.filter(surrounded);
    if (exact.length === 1) return exact[0]!;
    return positions.length === 1 ? positions[0]! : null;
  }
  const candidates = passage.context_before
    ? occurrences(passage.context_before).map((at) => at + passage.context_before.length)
    : [0];
  const exact = candidates.filter(surrounded);
  return exact.length === 1 ? exact[0]! : null;
}
