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
