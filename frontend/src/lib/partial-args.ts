/**
 * The fields of a tool call's arguments while they are still being written.
 *
 * A tool call's arguments stream as JSON text, a few characters at a time, and a
 * drawing has to be shown while that text is still an unfinished object - most
 * of it inside one long string. A JSON parser refuses all of it until the last
 * brace. This reads the top-level object as far as it goes and keeps every field
 * it has seen, the one being written included, with what has arrived of it.
 *
 * The known failure of the partial parsers this replaces is a buffer that ends
 * mid-escape silently dropping the whole value. Here an unfinished escape - a lone
 * backslash, half of `\uXXXX`, the first half of a surrogate pair - is held back
 * until the rest arrives, and everything before it is kept.
 */

export interface PartialField {
  value: unknown;
  /** The value's closing quote (or delimiter) has arrived. */
  complete: boolean;
}

const ESCAPES: Record<string, string> = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
};

/** A JSON string from `start` (just past its opening quote), as far as it goes. */
function readString(
  text: string,
  start: number,
): { value: string; end: number; complete: boolean } {
  let out = "";
  let i = start;
  while (i < text.length) {
    const char = text[i];
    if (char === '"') return { value: out, end: i + 1, complete: true };
    if (char !== "\\") {
      out += char;
      i += 1;
      continue;
    }
    const code = text[i + 1];
    if (code === undefined) break;
    if (code !== "u") {
      out += ESCAPES[code] ?? code;
      i += 2;
      continue;
    }
    const hex = text.slice(i + 2, i + 6);
    if (hex.length < 4) break;
    const unit = Number.parseInt(hex, 16);
    // The first half of a pair is held until the second half has arrived, so a
    // character outside the basic plane is never drawn as a broken glyph.
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const low = text.slice(i + 6, i + 12);
      if (low.length < 6) break;
      if (low.startsWith("\\u")) {
        out += String.fromCharCode(unit, Number.parseInt(low.slice(2), 16));
        i += 12;
        continue;
      }
    }
    out += String.fromCharCode(unit);
    i += 6;
  }
  return { value: out, end: text.length, complete: false };
}

function skipSpace(text: string, start: number): number {
  let i = start;
  while (i < text.length && " \t\n\r".includes(text.charAt(i))) i += 1;
  return i;
}

/** A non-string value: its raw text up to the next delimiter at its own depth. */
function readOther(
  text: string,
  start: number,
): { value: unknown; end: number; complete: boolean } {
  let depth = 0;
  let i = start;
  let inString = false;
  while (i < text.length) {
    const char = text[i];
    if (inString) {
      if (char === "\\") i += 1;
      else if (char === '"') inString = false;
    } else if (char === '"') inString = true;
    else if (char === "{" || char === "[") depth += 1;
    else if (char === "}" || char === "]") {
      if (depth === 0) break;
      depth -= 1;
    } else if (char === "," && depth === 0) break;
    i += 1;
  }
  const raw = text.slice(start, i).trim();
  const complete = i < text.length;
  try {
    return { value: JSON.parse(raw), end: i, complete };
  } catch {
    return { value: undefined, end: i, complete: false };
  }
}

/**
 * Every top-level field of a JSON object written so far.
 *
 * Text that is not the start of an object gives nothing; a field whose name has
 * not finished arriving is not yet a field.
 */
export function partialArgs(text: string): Record<string, PartialField> {
  const fields: Record<string, PartialField> = {};
  let i = skipSpace(text, 0);
  if (text[i] !== "{") return fields;
  i += 1;
  while (i < text.length) {
    i = skipSpace(text, i);
    if (text[i] === ",") i = skipSpace(text, i + 1);
    if (text[i] !== '"') break;
    const key = readString(text, i + 1);
    if (!key.complete) break;
    i = skipSpace(text, key.end);
    if (text[i] !== ":") break;
    i = skipSpace(text, i + 1);
    if (i >= text.length) break;
    const read = text[i] === '"' ? readString(text, i + 1) : readOther(text, i);
    if (read.value !== undefined || read.complete) {
      fields[key.value] = { value: read.value, complete: read.complete };
    }
    if (!read.complete) break;
    i = read.end;
  }
  return fields;
}
