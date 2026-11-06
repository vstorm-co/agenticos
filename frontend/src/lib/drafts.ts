/**
 * Drafts: what a `write_draft` call shows, from its arguments.
 *
 * A draft lives in the call that wrote it - the backend keeps no copy - so this
 * side reads the card back from the stored arguments, the way `lib/visuals.ts`
 * reads a drawing. The names are those of `app/agents/capabilities/drafts/_spec.py`.
 */

import type { ToolCall } from "@/types";

export const WRITE_DRAFT = "write_draft";

export interface DraftField {
  name: string | null;
  text: string;
  format: string;
}

export interface DraftVersion {
  label: string | null;
  fields: DraftField[];
}

export interface DraftCard {
  id: string;
  title: string;
  kind: string;
  versions: DraftVersion[];
}

/**
 * Whether a finished call wrote a draft: its result opens on what the tool says
 * when it did - the backend's `DRAFTED`. A last attempt's refusal is a finished
 * call too, and writes nothing.
 */
export function wroteDraft(result: unknown): boolean {
  return typeof result === "string" && /^Drafted /.test(result);
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function fieldOf(value: unknown): DraftField | null {
  const field = record(value);
  if (field === null || typeof field.text !== "string") return null;
  return {
    name: typeof field.name === "string" && field.name.trim() !== "" ? field.name : null,
    text: field.text,
    format: typeof field.format === "string" ? field.format : "text",
  };
}

function versionOf(value: unknown): DraftVersion | null {
  const version = record(value);
  if (version === null || !Array.isArray(version.fields) || version.fields.length === 0) {
    return null;
  }
  const fields = version.fields.map(fieldOf);
  if (fields.some((field) => field === null)) return null;
  return {
    label: typeof version.label === "string" ? version.label : null,
    fields: fields as DraftField[],
  };
}

/** The card a finished `write_draft` call shows, or null when it shows none. */
export function draftOf(call: ToolCall): DraftCard | null {
  if (
    call.status !== "completed" ||
    !wroteDraft(call.result) ||
    call.presentation_kind !== "draft"
  ) {
    return null;
  }
  const { title, kind, versions } = call.args;
  if (typeof title !== "string" || typeof kind !== "string") return null;
  if (!Array.isArray(versions) || versions.length === 0) return null;
  const parsed = versions.map(versionOf);
  if (parsed.some((version) => version === null)) return null;
  return { id: call.id, title, kind, versions: parsed as DraftVersion[] };
}

export function draftsOf(calls: readonly ToolCall[]): DraftCard[] {
  return calls.flatMap((call) => {
    const card = draftOf(call);
    return card === null ? [] : [card];
  });
}

/** A field's text without the blank lines around it; nothing inside changes. */
export function copyableText(text: string): string {
  return text.replace(/^(?:[ \t]*\r?\n)+/, "").replace(/(?:\r?\n[ \t]*)+$/, "");
}

/**
 * One version as text. Its label gets a blank line after it, not a single
 * newline: a label followed by a named field would otherwise run into the
 * field's name as if both were one line of the same part.
 */
function versionAsText(version: DraftVersion, labelled: boolean): string {
  const blocks = version.fields.map((field) =>
    field.name === null ? copyableText(field.text) : `${field.name}\n${copyableText(field.text)}`,
  );
  if (labelled && version.label !== null) blocks.unshift(version.label);
  return blocks.join("\n\n");
}

/** The drafts as one plain text, for a message's own Copy button. */
export function draftsAsText(cards: readonly DraftCard[]): string {
  return cards
    .map((card) =>
      card.versions.map((version) => versionAsText(version, card.versions.length > 1)).join("\n\n"),
    )
    .join("\n\n");
}

/** A message's text followed by its drafts, empty parts dropped. */
export function withDraftText(content: string | undefined, cards: readonly DraftCard[]): string {
  return [content ?? "", draftsAsText(cards)].filter((part) => part !== "").join("\n\n");
}

export interface DraftTextPart {
  text: string;
  placeholder: boolean;
}

// A fence, then an inline span: brackets inside either are syntax, not a gap to fill.
// Only a closed fence is code: in a `text` part an unclosed one is just backticks.
const CODE = /```[\s\S]*?```|``[^\n]*?``|`[^`\n]*`/g;
// [2-60 characters]; markdown links and references are told apart in placeholderParts.
const BRACKETED = /\[([^[\]\n]{2,60})\]/gu;
// A reference definition's tail: ": " and one target with a slash, dot or colon in it.
const DEFINITION = /^: *[^\s:/.]*[:/.]\S*\s*(?:\n|$)/;

function isPlaceholder(inner: string): boolean {
  return (
    /\p{L}/u.test(inner) && !/^[\^!]/.test(inner) && !inner.includes("://") && !/^cid:/.test(inner)
  );
}

/**
 * A draft's text as runs of plain text and placeholders ("[Your Name]"): the
 * details the agent left for the person to fill in. The parts' texts joined are
 * the input, so copying is unaffected. Only `text` and `markdown` are scanned -
 * brackets are syntax in any other format - and links, footnotes, quoted lines
 * and code are never placeholders. Anything else in brackets with a letter in it
 * is: a false flag costs a glance, a missed one a draft sent unfilled.
 */
export function placeholderParts(text: string, format: string): DraftTextPart[] {
  if (text === "") return [];
  if (format !== "text" && format !== "markdown") return [{ text, placeholder: false }];
  const masked = text.replace(CODE, (code) => " ".repeat(code.length));
  const parts: DraftTextPart[] = [];
  let last = 0;
  for (const match of masked.matchAll(BRACKETED)) {
    const start = match.index;
    const end = start + match[0].length;
    const lineStart = masked.lastIndexOf("\n", start - 1) + 1;
    const before = masked.slice(lineStart, start);
    if (masked[start - 1] === "[" && masked[end] === "]") continue;
    if (before.trimStart().startsWith(">")) continue;
    if (
      format === "markdown" &&
      (/^[([]/.test(masked.slice(end)) ||
        masked[start - 1] === "]" ||
        (/^ {0,3}$/.test(before) && DEFINITION.test(masked.slice(end))))
    ) {
      continue;
    }
    if (!isPlaceholder(match[1]!)) continue;
    if (start > last) parts.push({ text: text.slice(last, start), placeholder: false });
    parts.push({ text: match[0], placeholder: true });
    last = end;
  }
  if (last < text.length) parts.push({ text: text.slice(last), placeholder: false });
  return parts;
}
