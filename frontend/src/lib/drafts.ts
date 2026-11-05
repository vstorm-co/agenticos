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
  if (call.name !== WRITE_DRAFT || call.status !== "completed" || !wroteDraft(call.result)) {
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
