/**
 * A rule that could check what a grading criterion asks, read from the
 * criterion's own words with no model involved: a length, JSON, an opening, a
 * bulleted list. A rule grades the same answer the same way every time, which a
 * judge does not, so a criterion a rule can check is better checked by one.
 */

import type { CaseCheck, LengthCheck } from "@/types/datasets";

/**
 * A rule a criterion could be checked by, and what it checks - which the
 * component that offers it says in words: `text` is the opening `startsWith` wants.
 */
export type CheckSuggestion =
  | { kind: "length" | "json" | "bullets"; check: CaseCheck }
  | { kind: "startsWith"; check: CaseCheck; text: string };

const NUMBER = String.raw`(\d{1,3}(?:,\d{3})+|\d+)`;
const UNIT = String.raw`(words?|char(?:acter)?s?)\b`;
const AT_MOST = String.raw`(?:at most|no more than|not more than|no longer than|under|fewer than|less than|shorter than|maximum of|max(?:imum)?|up to|within)`;
const AT_LEAST = String.raw`(?:at least|no fewer than|no less than|not less than|no shorter than|minimum of|min(?:imum)?|more than|over|longer than)`;

/** "no more than" is a most and "no shorter than" a least: the bare comparison after "no" is not. */
const UNNEGATED = String.raw`(?<!\b(?:no|not)\s)`;

const BETWEEN = new RegExp(
  String.raw`\bbetween\s+${NUMBER}\s+(?:and|to|-)\s+${NUMBER}\s+${UNIT}`,
  "i",
);
const MOST = [
  new RegExp(String.raw`${UNNEGATED}\b${AT_MOST}\s+${NUMBER}\s+${UNIT}`, "i"),
  new RegExp(String.raw`\b${NUMBER}\s+${UNIT}\s+or\s+(?:fewer|less|shorter)\b`, "i"),
];
const LEAST = [
  new RegExp(String.raw`${UNNEGATED}\b${AT_LEAST}\s+${NUMBER}\s+${UNIT}`, "i"),
  new RegExp(String.raw`\b${NUMBER}\s+${UNIT}\s+or\s+(?:more|longer)\b`, "i"),
];
const STARTS =
  /\b(?:starts?|begins?|opens?)\s+with\s+(?:the\s+(?:word|phrase|text)\s+)?["“'‘]([^"”'’]+)["”'’]/i;
const BULLETS = /\bbullet(?:ed)?[\s-]+(?:list|points?)\b|\bbullets\b/i;
const JSON_ANSWER = /\bjson\b/i;
const NOT_JSON = /\b(?:not|never|no|without)\b[^.]{0,30}\bjson\b/i;

/** A pattern that matches a bulleted line anywhere in the answer. */
export const BULLET_PATTERN = String.raw`(?m)^\s*[-*•]`;

function count(text: string): number {
  return Number(text.replaceAll(",", ""));
}

function unitOf(text: string): "words" | "characters" {
  return text.toLowerCase().startsWith("word") ? "words" : "characters";
}

function bound(
  text: string,
  patterns: RegExp[],
): { value: number; unit: "words" | "characters" } | null {
  for (const pattern of patterns) {
    const found = pattern.exec(text);
    if (found) return { value: count(found[1]!), unit: unitOf(found[2]!) };
  }
  return null;
}

function length(text: string): LengthCheck | null {
  const between = BETWEEN.exec(text);
  if (between) {
    const [low, high] = [count(between[1]!), count(between[2]!)].sort((a, b) => a - b);
    return { type: "length", unit: unitOf(between[3]!), min: low, max: high };
  }
  const most = bound(text, MOST);
  const least = bound(text, LEAST);
  if (most && least && most.unit === least.unit && least.value <= most.value) {
    return { type: "length", unit: most.unit, min: least.value, max: most.value };
  }
  if (most) return { type: "length", unit: most.unit, max: most.value };
  if (least) return { type: "length", unit: least.unit, min: least.value };
  return null;
}

/** `text` as a regular expression that matches exactly it. */
export function escapePattern(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The rule that could check a criterion, or null when its words name nothing a
 * rule can check. Reads the criterion's name and description together; the
 * first that matches of a length, an opening, a bulleted list and JSON wins.
 */
export function suggestCheck(criterion: {
  name: string;
  description: string;
}): CheckSuggestion | null {
  const text = `${criterion.name}. ${criterion.description}`;
  const limit = length(text);
  if (limit) return { kind: "length", check: limit };
  const opening = STARTS.exec(text);
  if (opening) {
    const start = opening[1]!.trim();
    if (start !== "") {
      return {
        kind: "startsWith",
        text: start,
        check: { type: "regex", value: `^${escapePattern(start)}` },
      };
    }
  }
  if (BULLETS.test(text))
    return { kind: "bullets", check: { type: "regex", value: BULLET_PATTERN } };
  if (JSON_ANSWER.test(text) && !NOT_JSON.test(text)) {
    return { kind: "json", check: { type: "json_schema", schema: { type: "object" } } };
  }
  return null;
}
