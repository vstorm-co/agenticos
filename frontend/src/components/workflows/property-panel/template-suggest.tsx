"use client";

import { useTranslations } from "next-intl";

import type { StepData } from "@/lib/workflows/step-data";
import { placeholderText } from "@/lib/workflows/template-text";
import type { Uuid } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";

import type { SourceCandidate } from "./bindings";

/** One value a placeholder can name, as the list under a template box offers it. */
export interface Suggestion {
  /** The placeholder written out: `{{Step.path}}`. */
  text: string;
  step: string;
  /** `.path` into the step's output; empty for the whole of it. */
  path: string;
  /** What it holds - the declared type, or what a test run saw. */
  type: string;
}

/** How deep a run's data is offered inside a value with no declared shape. */
const OBSERVED_DEPTH = 3;
/** The most the list shows at once; typing narrows it. */
export const SHOWN_SUGGESTIONS = 50;

function typeOfSeen(value: unknown): string {
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  return typeof value;
}

/** Every path a run's value has inside it, a few levels deep, with what it held. */
function seenPaths(value: unknown, depth = 0): { path: string[]; type: string }[] {
  if (depth >= OBSERVED_DEPTH || typeof value !== "object" || value === null) return [];
  if (Array.isArray(value)) return [];
  return Object.entries(value).flatMap(([key, inner]) => [
    { path: [key], type: typeOfSeen(inner) },
    ...seenPaths(inner, depth + 1).map((found) => ({ ...found, path: [key, ...found.path] })),
  ]);
}

/**
 * What a placeholder in this field can name: the values the **Data** menu offers,
 * and inside a value with no declared shape - a payload, a loop's item - the
 * fields the last test run saw in it, which is usually what is meant.
 */
export function templateSuggestions(
  candidates: readonly SourceCandidate[],
  stepData: Readonly<Record<Uuid, StepData>>,
  names: ReadonlyMap<Uuid, string>,
): Suggestion[] {
  const seen = new Set<string>();
  const out: Suggestion[] = [];
  const add = (nodeId: Uuid, path: readonly string[], type: string) => {
    const text = placeholderText(nodeId, path, names);
    if (seen.has(text)) return;
    seen.add(text);
    const step = names.get(nodeId) ?? nodeId;
    out.push({ text, step, path: path.map((part) => `.${part}`).join(""), type });
  };
  for (const candidate of candidates) {
    add(candidate.nodeId, candidate.fieldPath, candidate.typeToken);
    if (!candidate.dynamic) continue;
    let value: unknown = stepData[candidate.nodeId]?.output ?? null;
    for (const part of candidate.fieldPath) {
      value =
        typeof value === "object" && value !== null
          ? (value as Record<string, unknown>)[part]
          : null;
    }
    for (const found of seenPaths(value)) {
      add(candidate.nodeId, [...candidate.fieldPath, ...found.path], found.type);
    }
  }
  return out;
}

/** The suggestions matching what was typed after `{{`: a name that starts with it first. */
export function matchSuggestions(suggestions: readonly Suggestion[], query: string): Suggestion[] {
  const wanted = query.toLowerCase();
  const inner = (suggestion: Suggestion) => `${suggestion.step}${suggestion.path}`.toLowerCase();
  return suggestions
    .filter((suggestion) => inner(suggestion).includes(wanted))
    .sort((a, b) => Number(inner(b).startsWith(wanted)) - Number(inner(a).startsWith(wanted)))
    .slice(0, SHOWN_SUGGESTIONS);
}

/**
 * The list under a template box while a placeholder is being written. The box
 * keeps the focus - arrows move through the list from it - so an option is
 * picked on mouse down, before the box would lose it.
 */
export function SuggestionList({
  id,
  suggestions,
  active,
  onPick,
}: {
  id: string;
  suggestions: readonly Suggestion[];
  active: number;
  onPick: (suggestion: Suggestion) => void;
}) {
  const t = useTranslations("workflows");
  return (
    <ul
      id={id}
      role="listbox"
      aria-label={t("templateSuggestions")}
      className="bg-popover text-popover-foreground border-border absolute top-full left-0 z-30 mt-1 max-h-56 w-full max-w-md overflow-y-auto rounded-md border p-1 shadow-md"
    >
      {suggestions.map((suggestion, index) => (
        <li
          key={suggestion.text}
          id={`${id}-${index}`}
          role="option"
          aria-selected={index === active}
          onMouseDown={(event) => {
            event.preventDefault();
            onPick(suggestion);
          }}
          className={cn(
            "flex cursor-pointer items-baseline justify-between gap-3 rounded-sm px-2 py-1 text-sm",
            index === active && "bg-accent",
          )}
        >
          <span className="min-w-0 truncate">
            <span className="text-[var(--domain-build)]">{suggestion.step}</span>
            <span className="text-[var(--domain-workspace)]">{suggestion.path}</span>
          </span>
          <span className="text-muted-foreground shrink-0 font-mono text-[11px]">
            {suggestion.type}
          </span>
        </li>
      ))}
    </ul>
  );
}
