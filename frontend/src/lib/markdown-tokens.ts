/**
 * Markdown source, split into what each part of it is - for drawing the source
 * itself, not for rendering it.
 *
 * The editor's underlay draws the very characters the textarea holds, so every
 * piece of text comes back exactly once and in order: the markers (`#`, `**`,
 * `` ` ``, `[`) are kept as their own pieces, to be dimmed rather than removed.
 * Joining every piece of every line with newlines gives the input back, which is
 * the invariant that keeps the colours on the words.
 *
 * Deliberately small: the block shapes a prompt or a skill is written in, and
 * the inline ones inside them. It is a highlighter, so a construct it does not
 * know is plain text, never an error.
 */

/** What one piece of a line is. */
export type MdStyle =
  "plain" | "marker" | "strong" | "emphasis" | "code" | "link" | "url" | "variable";

/** What a whole line is. */
export type MdLineKind =
  "text" | "heading" | "list" | "quote" | "fence" | "code" | "rule" | "table";

export interface MdPiece {
  text: string;
  style: MdStyle;
}

export interface MdLine {
  kind: MdLineKind;
  /** 1-6 on a heading, 0 otherwise. */
  level: number;
  pieces: MdPiece[];
}

const HEADING = /^(\s{0,3}#{1,6})(\s+.*|$)/;
const LIST = /^(\s*)([-*+]|\d+[.)])(\s+)(.*)$/;
const QUOTE = /^(\s*>+\s?)(.*)$/;
const FENCE = /^\s*(```|~~~)/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const TABLE = /^\s*\|.*\|\s*$/;

/**
 * The inline constructs, longest first, as one alternation scanned left to
 * right; each capturing group is one construct. Underscores count only at a
 * word's edge, because a prompt is full of `write_memory` and `snake_case` that
 * are names, not emphasis.
 */
const INLINE =
  /(\{\{[a-zA-Z_][\w.]*\}\})|(`+)([^`]+?)\2|(\*\*|(?<!\w)__)(?=\S)(.+?)(?<=\S)\4(?!\w)|(\*|(?<!\w)_)(?=\S)(.+?)(?<=\S)\6(?!\w)|(\[)([^\]\n]+)(\]\()([^)\s]+)(\))/g;

/** The inline pieces of one run of text, every character accounted for. */
export function inlinePieces(text: string, base: MdStyle = "plain"): MdPiece[] {
  const pieces: MdPiece[] = [];
  const push = (piece: string, style: MdStyle) => {
    if (piece) pieces.push({ text: piece, style });
  };
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    const start = match.index;
    push(text.slice(at, start), base);
    const [
      whole,
      variable,
      ticks,
      code,
      strongMark,
      strong,
      emMark,
      em,
      open,
      label,
      middle,
      url,
      close,
    ] = match;
    if (variable) {
      push(variable, "variable");
    } else if (ticks && code !== undefined) {
      push(ticks, "marker");
      push(code, "code");
      push(ticks, "marker");
    } else if (strongMark && strong !== undefined) {
      push(strongMark, "marker");
      push(strong, "strong");
      push(strongMark, "marker");
    } else if (emMark && em !== undefined) {
      push(emMark, "marker");
      push(em, "emphasis");
      push(emMark, "marker");
    } else if (open && label !== undefined && middle && url !== undefined && close) {
      push(open, "marker");
      push(label, "link");
      push(middle, "marker");
      push(url, "url");
      push(close, "marker");
    }
    at = start + whole.length;
  }
  push(text.slice(at), base);
  return pieces;
}

/** The pieces of a table row: its pipes dimmed, its cells read inline. */
function tablePieces(line: string): MdPiece[] {
  const pieces: MdPiece[] = [];
  for (const part of line.split(/(\|)/)) {
    if (part === "|") pieces.push({ text: part, style: "marker" });
    else if (/^\s*:?-+:?\s*$/.test(part)) pieces.push({ text: part, style: "marker" });
    else pieces.push(...inlinePieces(part));
  }
  return pieces;
}

/** Every line of `text`, with what it is and its pieces. */
export function markdownLines(text: string): MdLine[] {
  let fenced = false;
  return text.split("\n").map((line): MdLine => {
    if (FENCE.test(line)) {
      fenced = !fenced;
      return { kind: "fence", level: 0, pieces: [{ text: line, style: "marker" }] };
    }
    // Inside a fence nothing is read, and the line as a whole is the code: the
    // inline `code` tint on every line drew a striped block.
    if (fenced) return { kind: "code", level: 0, pieces: [{ text: line, style: "plain" }] };

    const heading = HEADING.exec(line);
    if (heading) {
      const marks = heading[1]!;
      return {
        kind: "heading",
        level: marks.trim().length,
        pieces: [{ text: marks, style: "marker" }, ...inlinePieces(heading[2]!, "strong")],
      };
    }
    if (RULE.test(line))
      return { kind: "rule", level: 0, pieces: [{ text: line, style: "marker" }] };
    if (TABLE.test(line)) return { kind: "table", level: 0, pieces: tablePieces(line) };

    const list = LIST.exec(line);
    if (list) {
      return {
        kind: "list",
        level: 0,
        pieces: [
          { text: `${list[1]}${list[2]}${list[3]}`, style: "marker" },
          ...inlinePieces(list[4]!),
        ],
      };
    }
    const quote = QUOTE.exec(line);
    if (quote) {
      return {
        kind: "quote",
        level: 0,
        pieces: [{ text: quote[1]!, style: "marker" }, ...inlinePieces(quote[2]!, "emphasis")],
      };
    }
    return { kind: "text", level: 0, pieces: inlinePieces(line) };
  });
}
