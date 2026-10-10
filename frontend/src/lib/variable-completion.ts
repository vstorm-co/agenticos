/**
 * Completing `{{variable}}` in an agent's instructions (#2065).
 *
 * Pure functions over the text and the caret, so the editor stays a thin shell
 * and the parts that decide what is open and what gets inserted are testable.
 */

export interface OpenVariable {
  /** Where the `{{` starts. */
  start: number;
  /** What has been typed after it so far. */
  query: string;
  /** Where the caret is - the end of what gets replaced. */
  end: number;
}

const NAME_SO_FAR = /^\s*[a-z0-9_]*$/;

/** The variable being typed at `caret`, if the caret sits inside an unclosed `{{`. */
export function openVariable(text: string, caret: number): OpenVariable | null {
  const before = text.slice(0, caret);
  const start = before.lastIndexOf("{{");
  if (start < 0) return null;
  const query = before.slice(start + 2);
  if (!NAME_SO_FAR.test(query)) return null;
  return { start, query: query.trim(), end: caret };
}

/** The names worth offering for `query`: those starting with it, then those containing it. */
export function matching<T extends { name: string }>(options: T[], query: string): T[] {
  const starts = options.filter((option) => option.name.startsWith(query));
  const contains = options.filter(
    (option) => !option.name.startsWith(query) && option.name.includes(query),
  );
  return [...starts, ...contains];
}

/** `text` with the open variable replaced by `{{name}}`, and where the caret goes. */
export function insertVariable(
  text: string,
  caret: number,
  open: OpenVariable | null,
  name: string,
): { text: string; caret: number } {
  const start = open ? open.start : caret;
  const after = text.slice(caret);
  const rest = open && after.startsWith("}}") ? after.slice(2) : after;
  const token = `{{${name}}}`;
  return { text: `${text.slice(0, start)}${token}${rest}`, caret: start + token.length };
}

/** The variable names `text` uses, each once. */
export function usedVariables(text: string): string[] {
  return [...new Set([...text.matchAll(/\{\{\s*([a-z][a-z0-9_]*)\s*\}\}/g)].map((m) => m[1]!))];
}
