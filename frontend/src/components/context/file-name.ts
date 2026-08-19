/**
 * What a context file is called and what it is - the two halves the API keeps in
 * separate columns, and the one place the console reasons about either.
 */

/**
 * The formats a context file may declare.
 *
 * The list the API's own field description names (`app/schemas/context.py`:
 * "a hint for fencing and rendering, e.g. md, txt, json, yaml, csv"), which is
 * also every format `resolveFileKind` can render a preview for. It was a text
 * input, so `markdown`, `MD` and a typo were all accepted and only one of them
 * rendered - a free-text field whose value decides how something is drawn is a
 * field that silently draws it wrong.
 */
export const FORMATS = ["md", "txt", "json", "yaml", "csv"] as const;

export type ContextFormat = (typeof FORMATS)[number];

/** The default, matching the API's own. */
export const DEFAULT_FORMAT: ContextFormat = "md";

/** The other spellings of a format this platform stores under one name. */
const ALIASES: Record<string, ContextFormat> = { markdown: "md", yml: "yaml", text: "txt" };

/**
 * The format this word names, or `null` where it names none of them.
 *
 * The strict half, for a caller that has to be able to *refuse*: a dropped
 * `page.html` is text, and a context file has no format that means HTML.
 */
function recognized(word: string): ContextFormat | null {
  const value = word.trim().toLowerCase();
  if ((FORMATS as readonly string[]).includes(value)) return value as ContextFormat;
  return ALIASES[value] ?? null;
}

/**
 * The format a stored file's value maps onto, for a select that must show one.
 *
 * A file written before the select existed can hold anything the column allowed,
 * and a `<Select>` given a value with no option renders empty - which reads as
 * "no format" for a file that has one. `markdown` and `yml` are the two spellings
 * worth recognising; anything else falls back to the default rather than to a
 * blank control.
 */
export function toFormat(stored: string): ContextFormat {
  return recognized(stored) ?? DEFAULT_FORMAT;
}

/**
 * The name a reader and the renderer both see.
 *
 * A context file's name carries no extension - `glossary`, not `glossary.md` -
 * and the format is a separate field. But which renderer opens is decided from a
 * filename (`resolveFileKind`), so a Markdown body reached the pane as an unknown
 * kind and rendered as plain text. Composed rather than stored, and only where
 * the name does not already end in it, so a file somebody called `notes.md` does
 * not become `notes.md.md`.
 */
export function displayName(name: string, format: string): string {
  const suffix = format.trim();
  if (suffix === "" || name.toLowerCase().endsWith(`.${suffix.toLowerCase()}`)) return name;
  return `${name}.${suffix}`;
}

/** What a filename decides on its own: the two fields, without the body. */
export type ContextDraftFields = Pick<ContextDraft, "name" | "format">;

/** A dropped file, as the fields a new context file would start from. */
export interface ContextDraft {
  /** Distinguishes one queued draft from the next; the dialog is keyed on it. */
  key: string;
  name: string;
  format: ContextFormat;
  content: string;
}

/**
 * A dropped file, as the name and format a context file would take - or `null`.
 *
 * The extension decides the format and then leaves the name, because it is
 * carried by the `format` column: `runbook.md` becomes `runbook` + `md`, and a
 * file with no extension keeps its whole name and the default format. Names are
 * lower-cased and spaces become hyphens - the name is a handle a tool call
 * quotes, not a title.
 *
 * `null` for an extension no format names. `readsAsText` admits every textual
 * kind, HTML and source files included, and this field has five values - so a
 * dropped `page.html` used to arrive as a file called `page` whose HTML body was
 * labelled Markdown, silently changing how it is fenced for the model and
 * contradicting the overlay that says which formats are taken. Refusing is the
 * whole point of the return type: there is nothing to guess between an HTML
 * document and a Markdown one.
 */
export function draftFromFilename(
  filename: string,
): { name: string; format: ContextFormat } | null {
  const dot = filename.lastIndexOf(".");
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  const format = dot > 0 ? recognized(filename.slice(dot + 1)) : DEFAULT_FORMAT;
  if (format === null) return null;
  return { name: stem.toLowerCase().replace(/\s+/g, "-").slice(0, 64), format };
}
