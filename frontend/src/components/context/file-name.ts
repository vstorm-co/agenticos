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
  const value = stored.trim().toLowerCase();
  if ((FORMATS as readonly string[]).includes(value)) return value as ContextFormat;
  if (value === "markdown") return "md";
  if (value === "yml") return "yaml";
  if (value === "text") return "txt";
  return DEFAULT_FORMAT;
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

/** A dropped file, as the fields a new context file would start from. */
export interface ContextDraft {
  /** Distinguishes one queued draft from the next; the dialog is keyed on it. */
  key: string;
  name: string;
  format: ContextFormat;
  content: string;
}

/**
 * A dropped file, as the name and format a context file would take.
 *
 * The extension decides the format and then leaves the name, because it is
 * carried by the `format` column: `runbook.md` becomes `runbook` + `md`, and a
 * file with no extension keeps its whole name and the default format. Names are
 * lower-cased and spaces become hyphens - the name is a handle a tool call
 * quotes, not a title.
 */
export function draftFromFilename(filename: string): { name: string; format: ContextFormat } {
  const dot = filename.lastIndexOf(".");
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  const extension = dot > 0 ? filename.slice(dot + 1) : "";
  return {
    name: stem.toLowerCase().replace(/\s+/g, "-").slice(0, 64),
    format: toFormat(extension),
  };
}
