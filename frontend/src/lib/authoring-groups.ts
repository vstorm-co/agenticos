import type { Hunk, RejectedChange } from "@/types/authoring";

/** The kinds of change the assistant's card groups by, in the order they are shown. */
export const CHANGE_GROUPS = ["instructions", "tools", "settings", "skills"] as const;
export type ChangeGroup = (typeof CHANGE_GROUPS)[number];

export function changeGroup(kind: Hunk["kind"]): ChangeGroup {
  if (kind === "instructions") return "instructions";
  if (kind === "tool_override") return "tools";
  if (kind === "create_skill") return "skills";
  return "settings";
}

/** Whether a person reworded or re-set a suggestion before accepting it. */
export function editedOnAccept(hunk: Hunk): boolean {
  if (hunk.status !== "accepted") return false;
  if (hunk.kind === "instructions") {
    return hunk.accepted_text !== null && hunk.accepted_text !== hunk.new_text;
  }
  if (hunk.kind === "spec_field") {
    return (
      hunk.accepted_value !== null &&
      JSON.stringify(hunk.accepted_value) !== JSON.stringify(hunk.new_value)
    );
  }
  return false;
}

/**
 * Where a new skill the assistant wrote but did not add stands: waiting for a
 * person, created, or dismissed. Anything else it did not add is not a decision.
 */
export function ideaState(item: RejectedChange): "waiting" | "created" | "dismissed" | null {
  if (item.kind !== "create_skill") return null;
  if (item.skill_id) return "created";
  if (item.dismissed) return "dismissed";
  return item.change.content ? "waiting" : null;
}

const IDENTIFIER = /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}/i;
/** "(runs e38ca3e9-…, 3e1929d0-…)" - an aside naming runs, which a summary leaves out. */
const RUN_ASIDE = /\s*\([^)]*\b[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}[^)]*\)/gi;

/**
 * One sentence saying what a change is for: its expected effect, else the first
 * sentence of its rationale, without the runs it cites in passing. Empty when
 * every sentence names a run by its id, which a reader cannot follow from a
 * summary line.
 */
export function oneSentence(hunk: Pick<Hunk, "expected_effect" | "rationale">): string {
  const text = (hunk.expected_effect || hunk.rationale).replace(RUN_ASIDE, "").trim();
  return text.split(/(?<=[.!?])\s+/).find((sentence) => !IDENTIFIER.test(sentence)) ?? "";
}

/** Items in the fixed group order, each group with its members in their own order. */
export function grouped<T>(items: T[], groupOf: (item: T) => ChangeGroup): [ChangeGroup, T[]][] {
  return CHANGE_GROUPS.map(
    (group) => [group, items.filter((item) => groupOf(item) === group)] as [ChangeGroup, T[]],
  ).filter(([, members]) => members.length > 0);
}
