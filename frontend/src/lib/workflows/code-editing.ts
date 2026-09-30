/**
 * What the code editor's keys do to its text: pure functions from a text and a
 * selection to the next text and selection, so each rule is testable without a
 * browser, and the editor only applies what they return.
 */

export type CodeLanguage = "python" | "javascript";

export interface Edit {
  text: string;
  start: number;
  end: number;
}

/** How deep one level of indentation is: PEP 8's four spaces, and two for JavaScript. */
export function indentUnit(language: CodeLanguage): string {
  return language === "python" ? "    " : "  ";
}

const PAIRS: Record<string, string> = {
  "(": ")",
  "[": "]",
  "{": "}",
  '"': '"',
  "'": "'",
  "`": "`",
};
const CLOSERS = new Set([")", "]", "}"]);

function lineStart(text: string, index: number): number {
  return text.lastIndexOf("\n", index - 1) + 1;
}

/**
 * Tab and Shift+Tab. With no selection, Tab inserts one level at the caret; with
 * lines selected, either key moves every line of the selection a level, and
 * Shift+Tab takes away at most one level from each.
 */
export function indent(edit: Edit, language: CodeLanguage, outdent: boolean): Edit {
  const unit = indentUnit(language);
  const { text, start, end } = edit;
  if (!outdent && start === end) {
    return {
      text: text.slice(0, start) + unit + text.slice(end),
      start: start + unit.length,
      end: start + unit.length,
    };
  }
  const first = lineStart(text, start);
  const lines = text.slice(first, end).split("\n");
  let shiftStart = 0;
  let shiftTotal = 0;
  const moved = lines.map((line, index) => {
    if (!outdent) {
      shiftTotal += unit.length;
      if (index === 0) shiftStart = unit.length;
      return unit + line;
    }
    const leading = line.length - line.trimStart().length;
    const taken = Math.min(leading, unit.length);
    shiftTotal -= taken;
    if (index === 0) shiftStart = -Math.min(taken, start - first);
    return line.slice(taken);
  });
  const next = text.slice(0, first) + moved.join("\n") + text.slice(end);
  return { text: next, start: Math.max(first, start + shiftStart), end: end + shiftTotal };
}

/**
 * Enter: the new line keeps the indentation of the one it leaves, one level more
 * after a line that opens a block - a `:` in Python, an open bracket in either -
 * and a closing bracket right after the caret goes to a line of its own below.
 */
export function newline(edit: Edit, language: CodeLanguage): Edit {
  const { text, start, end } = edit;
  const first = lineStart(text, start);
  const before = text.slice(first, start);
  const indentation = before.slice(0, before.length - before.trimStart().length);
  const trimmed = before.trimEnd();
  const last = trimmed.at(-1);
  const opens =
    last === "(" || last === "[" || last === "{" || (language === "python" && last === ":");
  const inner = opens ? indentation + indentUnit(language) : indentation;
  const next = text[end];
  const closes = opens && next !== undefined && CLOSERS.has(next) && PAIRS[last as string] === next;
  const inserted = `\n${inner}` + (closes ? `\n${indentation}` : "");
  const caret = start + 1 + inner.length;
  return { text: text.slice(0, start) + inserted + text.slice(end), start: caret, end: caret };
}

/**
 * A typed bracket or quote. An opening one around a selection wraps it; with no
 * selection it inserts its pair, except a quote typed into a word; a closing one
 * typed where it already is steps over it. Returns null when the key is typed
 * as it is.
 */
export function typePair(edit: Edit, char: string): Edit | null {
  const { text, start, end } = edit;
  const steps = CLOSERS.has(char) || PAIRS[char] === char;
  if (steps && start === end && text[end] === char) {
    return { text, start: start + 1, end: start + 1 };
  }
  const close = PAIRS[char];
  if (close === undefined) return null;
  if (start !== end) {
    const wrapped = char + text.slice(start, end) + close;
    return {
      text: text.slice(0, start) + wrapped + text.slice(end),
      start: start + 1,
      end: end + 1,
    };
  }
  if (close === char && /\w/.test(text[start - 1] ?? "")) return null;
  return {
    text: text.slice(0, start) + char + close + text.slice(end),
    start: start + 1,
    end: start + 1,
  };
}

/** Backspace between an empty pair takes both halves; null leaves the key to the browser. */
export function erasePair(edit: Edit): Edit | null {
  const { text, start, end } = edit;
  if (start !== end || start === 0) return null;
  const open = text[start - 1] as string;
  if (PAIRS[open] === undefined || text[start] !== PAIRS[open]) return null;
  return {
    text: text.slice(0, start - 1) + text.slice(start + 1),
    start: start - 1,
    end: start - 1,
  };
}

/**
 * The `args` key being typed at the caret - after `args["`, `args['` or, in
 * JavaScript, `args.` - and where it starts, or null when the caret is in none.
 */
export function argKeyAt(
  text: string,
  caret: number,
  language: CodeLanguage,
): { prefix: string; from: number; quote: string | null } | null {
  const before = text.slice(0, caret);
  const quoted = /args\[(["'])(\w*)$/.exec(before);
  if (quoted !== null) {
    const prefix = quoted[2] as string;
    return { prefix, from: caret - prefix.length, quote: quoted[1] as string };
  }
  if (language === "javascript") {
    const dotted = /args\.(\w*)$/.exec(before);
    if (dotted !== null) {
      const prefix = dotted[1] as string;
      return { prefix, from: caret - prefix.length, quote: null };
    }
  }
  return null;
}

/** `key` completed into the text from `from` to the caret, closing a quoted key. */
export function completeArg(
  text: string,
  caret: number,
  at: { from: number; quote: string | null },
  key: string,
): Edit {
  const closing = at.quote === null ? "" : `${at.quote}]`;
  const rest = text.slice(caret);
  const already = at.quote !== null && rest.startsWith(closing);
  const inserted = key + (already ? "" : closing);
  const next = text.slice(0, at.from) + inserted + rest;
  const position = at.from + key.length + closing.length;
  return { text: next, start: position, end: position };
}

const OPENERS: Record<string, string> = { "(": ")", "[": "]", "{": "}" };
const OPENER_OF: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

/**
 * The bracket beside the caret and the one that matches it, as their indexes -
 * the one just before the caret first, as editors do - or null when neither
 * side is a bracket or it is unmatched. Counted by kind only: a bracket inside a
 * string counts too, which is the price of not parsing the language.
 */
export function matchingBracket(text: string, caret: number): [number, number] | null {
  for (const at of [caret - 1, caret]) {
    const char = text[at];
    if (char === undefined) continue;
    const closer = OPENERS[char];
    const opener = OPENER_OF[char];
    if (closer === undefined && opener === undefined) continue;
    const step = closer !== undefined ? 1 : -1;
    const same = char;
    const other = closer ?? (opener as string);
    let depth = 0;
    for (let index = at + step; index >= 0 && index < text.length; index += step) {
      if (text[index] === same) depth += 1;
      else if (text[index] === other) {
        if (depth === 0) return step === 1 ? [at, index] : [index, at];
        depth -= 1;
      }
    }
    return null;
  }
  return null;
}
