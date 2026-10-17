/**
 * The `@` in the composer: where a mention is being typed, and what matches it (#2189).
 *
 * Pure, so the composer's behaviour is tested without a textarea.
 */

import type { MentionKind, Mentionable } from "@/types/mention";

/** The order the menu groups them in: what the agent can call first, then who, then what it reads. */
export const MENTION_KIND_ORDER: readonly MentionKind[] = [
  "mcp",
  "agent",
  "collection",
  "skill",
  "context",
];

/** At most this many in the menu: a person narrows by typing, not by scrolling. */
export const MENTION_MENU_LIMIT = 12;

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

/** What matches, grouped by kind and ranked by how the name starts, without what is already picked. */
export function matching(
  items: readonly Mentionable[],
  query: string,
  picked: readonly Mentionable[],
): Mentionable[] {
  const needle = query.toLowerCase();
  const taken = new Set(picked.map((item) => `${item.kind}:${item.id}`));
  const rank = (item: Mentionable) => {
    const name = item.name.toLowerCase();
    if (name.startsWith(needle)) return 0;
    return name.includes(needle) ? 1 : 2;
  };
  return items
    .filter((item) => !taken.has(`${item.kind}:${item.id}`) && rank(item) < 2)
    .sort(
      (left, right) =>
        MENTION_KIND_ORDER.indexOf(left.kind) - MENTION_KIND_ORDER.indexOf(right.kind) ||
        rank(left) - rank(right),
    )
    .slice(0, MENTION_MENU_LIMIT);
}

/** The text without the typed `@query`, and where the caret goes after it. */
export function withoutQuery(text: string, at: MentionQuery): { text: string; caret: number } {
  const end = at.start + 1 + at.query.length;
  return { text: text.slice(0, at.start) + text.slice(end), caret: at.start };
}
