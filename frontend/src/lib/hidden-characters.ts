/**
 * Control and format characters (Cc, Cf) other than a newline and a tab: the
 * ones that draw nothing or reorder what is around them, such as U+202E or a
 * zero-width space.
 */
const HIDDEN = /(?![\n\t])[\p{Cc}\p{Cf}]/gu;

/**
 * `text` as a person has to read it to know what it says: every character that
 * would draw nothing or reorder the text around it written out as `\u{202E}`.
 */
export function writtenOut(text: string): string {
  // Each regex match contains one complete code point.
  return text.replace(HIDDEN, (char) => `\\u{${char.codePointAt(0)!.toString(16).toUpperCase()}}`);
}

/**
 * Whether a text, or any text inside a JSON value with its keys, holds a character
 * `writtenOut` would write out - before serializing escapes a control character.
 */
export function holdsHidden(value: unknown): boolean {
  if (typeof value === "string") return writtenOut(value) !== value;
  if (Array.isArray(value)) return value.some(holdsHidden);
  if (value !== null && typeof value === "object")
    return Object.entries(value).some(([key, item]) => holdsHidden(key) || holdsHidden(item));
  return false;
}
