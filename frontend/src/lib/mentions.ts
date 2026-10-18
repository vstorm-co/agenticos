/**
 * The `@` in the composer: where a mention is being typed, and what matches it (#2189).
 *
 * Pure, so the composer's behaviour is tested without a textarea.
 */

import type { MentionKind, Mentionable } from "@/types/mention";

/** The order the menu groups them in: servers, who it hands work to, what it can do, how, and what it reads. */
export const MENTION_KIND_ORDER: readonly MentionKind[] = [
  "mcp",
  "agent",
  "capability",
  "skill",
  "collection",
  "context",
  "project",
];

/** A mention being typed: where its `@` is, and what follows it. */
export interface MentionQuery {
  start: number;
  query: string;
}

/**
 * The mention being typed at the caret, if any.
 *
 * An `@` opening the text or following whitespace, then up to 40 characters with
 * no whitespace or second `@` - so an address like `ann@example.com` is never one.
 */
export function mentionAt(text: string, caret: number): MentionQuery | null {
  const before = text.slice(0, caret);
  if (!/(^|\s)@[^\s@]{0,40}$/.test(before)) return null;
  const start = before.lastIndexOf("@");
  return { start, query: before.slice(start + 1) };
}

/** A name as typed against: case, spaces, `_` and `-` do not count, so `websearc` finds `web_search`. */
function folded(text: string): string {
  return text.toLowerCase().replace(/[\s_-]+/g, "");
}

/**
 * Everything that matches - the menu scrolls - grouped by kind and ranked by how
 * the name starts. What is already picked stays offered: naming it twice is the
 * person's choice, and a menu that loses a row on use reads as broken.
 */
export function matching(items: readonly Mentionable[], query: string): Mentionable[] {
  const needle = folded(query);
  const rank = (item: Mentionable) => {
    const name = folded(item.name);
    if (name.startsWith(needle)) return 0;
    return name.includes(needle) ? 1 : 2;
  };
  return items
    .filter((item) => rank(item) < 2)
    .sort(
      (left, right) =>
        MENTION_KIND_ORDER.indexOf(left.kind) - MENTION_KIND_ORDER.indexOf(right.kind) ||
        rank(left) - rank(right),
    );
}

/** What the composer writes for a picked mention, and what it looks for to keep it. */
export function mentionToken(item: Mentionable): string {
  return `@${item.name}`;
}

/**
 * The typed `@query` replaced by the mention's token and one space, and where the
 * caret goes: after that space, so the next word is not read as more of the name.
 */
export function insertMention(
  text: string,
  at: MentionQuery,
  item: Mentionable,
): { text: string; caret: number } {
  const token = `${mentionToken(item)} `;
  const rest = text.slice(at.start + 1 + at.query.length).replace(/^ /, "");
  return { text: text.slice(0, at.start) + token + rest, caret: at.start + token.length };
}

/** One run of a message: plain text, or a picked mention's token. */
export interface MentionSegment {
  text: string;
  item?: Mentionable;
}

function escaped(name: string): string {
  return name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The text cut at each picked mention's token - `@Notion` where an `@` opens the
 * text or follows whitespace, and nothing but punctuation or space comes after.
 * Longer names first, so `@Notion Work` is not read as `@Notion` and a stray word.
 */
export function mentionSegments(text: string, picked: readonly Mentionable[]): MentionSegment[] {
  if (picked.length === 0) return text ? [{ text }] : [];
  const byName = new Map(picked.map((item) => [item.name, item]));
  const names = [...byName.keys()].sort((left, right) => right.length - left.length);
  const pattern = new RegExp(
    `(^|\\s)@(${names.map(escaped).join("|")})(?=$|[^\\p{L}\\p{N}_])`,
    "gu",
  );
  const segments: MentionSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index + match[1]!.length;
    if (start > cursor) segments.push({ text: text.slice(cursor, start) });
    const name = match[2]!;
    segments.push({ text: `@${name}`, item: byName.get(name) });
    cursor = start + 1 + name.length;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments;
}

/** The picked mentions whose token is still in the text: deleting `@Notion` unpicks it. */
export function stillMentioned(text: string, picked: readonly Mentionable[]): Mentionable[] {
  const present = new Set(
    mentionSegments(text, picked).flatMap((segment) => (segment.item ? [segment.item] : [])),
  );
  return picked.filter((item) => present.has(item));
}
