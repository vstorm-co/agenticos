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
  return text.replace(
    HIDDEN,
    (char) => `\\u{${(char.codePointAt(0) ?? 0).toString(16).toUpperCase()}}`,
  );
}
