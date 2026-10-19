import type { StepData } from "./step-data";
import type { NodeOutputRef, TemplateValue, Uuid } from "./types";

/** `{{ Step name.field.path }}` - a placeholder as an author writes one. */
const PLACEHOLDER = /\{\{\s*([^{}]*?)\s*\}\}/g;

/** One placeholder as an author reads it: the step's name, then the path into its output. */
export function placeholderText(
  nodeId: Uuid,
  path: readonly string[],
  names: ReadonlyMap<Uuid, string>,
): string {
  return `{{${[names.get(nodeId) ?? nodeId, ...path].join(".")}}}`;
}

/** One run of an author's text: plain, or a whole `{{ ... }}` placeholder. */
export interface TemplateSegment {
  text: string;
  placeholder: boolean;
}

/**
 * An author's text cut where its placeholders start and end - what the editor
 * draws them apart by. Every character lands in exactly one segment, in order.
 */
export function templateSegments(text: string): TemplateSegment[] {
  const segments: TemplateSegment[] = [];
  let last = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    if (match.index > last)
      segments.push({ text: text.slice(last, match.index), placeholder: false });
    segments.push({ text: match[0], placeholder: true });
    last = match.index + match[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last), placeholder: false });
  return segments;
}

/**
 * The placeholder being written at `caret`: a `{{` before it with no `}}`, brace
 * or line break since - where it starts, and what is typed after the braces. Null
 * when the caret is not in one.
 */
export function openPlaceholderAt(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const start = before.lastIndexOf("{{");
  if (start === -1) return null;
  const typed = before.slice(start + 2);
  return /[{}\n]/.test(typed) ? null : { start, query: typed.trim() };
}

/**
 * `text` with the placeholder begun at `start` written out as `placeholder`, up
 * to the caret - and over the rest of it, where its closing braces are already
 * there - with where the caret goes after it.
 */
export function completePlaceholder(
  text: string,
  caret: number,
  start: number,
  placeholder: string,
): { text: string; caret: number } {
  const rest = /^[^{}\n]*\}\}/.exec(text.slice(caret));
  const end = caret + (rest?.[0].length ?? 0);
  return {
    text: `${text.slice(0, start)}${placeholder}${text.slice(end)}`,
    caret: start + placeholder.length,
  };
}

/** A template as the text an author edits: its text as it is, each placeholder by name. */
export function templateText(template: TemplateValue, names: ReadonlyMap<Uuid, string>): string {
  return template.parts
    .map((part) =>
      typeof part === "string" ? part : placeholderText(part.node_id, part.field_path, names),
    )
    .join("");
}

export type ParsedTemplate =
  | { parts: TemplateValue["parts"] }
  /** A placeholder naming no step in reach, or no value of it. */
  | { unknown: string };

/**
 * The parts an author's text stands for. Each placeholder names a step by the
 * longest of the names given that it starts with, then a path into its output;
 * `resolve` finds the reference that path is, or null when there is none.
 */
export function parseTemplate(
  text: string,
  names: ReadonlyMap<Uuid, string>,
  resolve: (nodeId: Uuid, path: string[]) => NodeOutputRef | null,
): ParsedTemplate {
  const byLength = [...names].sort(([, a], [, b]) => b.length - a.length);
  const parts: TemplateValue["parts"] = [];
  let last = 0;
  for (const match of text.matchAll(PLACEHOLDER)) {
    const inner = match[1] as string;
    const named = byLength.find(([, name]) => inner === name || inner.startsWith(`${name}.`));
    const ref =
      named === undefined
        ? null
        : resolve(
            named[0],
            inner
              .slice(named[1].length + 1)
              .split(".")
              .filter((segment) => segment !== ""),
          );
    if (ref === null) return { unknown: match[0] };
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(ref);
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return { parts };
}

/** What a template gives with the data the last test runs saw, and the placeholders they had nothing for. */
export function previewTemplate(
  template: TemplateValue,
  stepData: Record<Uuid, StepData>,
  names: ReadonlyMap<Uuid, string>,
): { text: string; missing: string[] } {
  const missing: string[] = [];
  const text = template.parts
    .map((part) => {
      if (typeof part === "string") return part;
      let value: unknown = stepData[part.node_id]?.output ?? null;
      for (const segment of part.field_path) {
        value =
          typeof value === "object" && value !== null
            ? ((value as Record<string, unknown>)[segment] ?? null)
            : null;
      }
      if (value === null) {
        const placeholder = placeholderText(part.node_id, part.field_path, names);
        missing.push(placeholder);
        return placeholder;
      }
      return typeof value === "string" ? value : JSON.stringify(value);
    })
    .join("");
  return { text, missing };
}
