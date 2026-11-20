import type { RoomMessageMention } from "@/types/conversation";
import type { RoomDraftMention, RoomParticipantRead, RoomParticipantRef } from "@/types/room";

export interface RoomMentionQuery {
  start: number;
  query: string;
}

/** Post-edit selection plus the textarea selection immediately before input. */
export interface RoomMentionEditHint {
  caret: number;
  selectionEnd: number;
  previousSelectionStart?: number;
  previousSelectionEnd?: number;
  inputType?: string;
}

/** A room-only @ query. This intentionally has no dependency on resource mentions. */
export function roomMentionAt(
  text: string,
  caret: number,
  selectionEnd = caret,
): RoomMentionQuery | null {
  if (caret !== selectionEnd) return null;
  const before = text.slice(0, caret);
  if (!/(^|\s)@[^\s@]{0,40}$/.test(before)) return null;
  const start = before.lastIndexOf("@");
  return { start, query: before.slice(start + 1) };
}

function folded(value: string): string {
  return value.toLowerCase().replace(/[\s_-]+/g, "");
}

export function matchingRoomMentionables(
  items: readonly RoomParticipantRead[],
  query: string,
): RoomParticipantRead[] {
  const needle = folded(query);
  const rank = (item: RoomParticipantRead) => {
    const name = folded(item.name);
    if (name.startsWith(needle)) return 0;
    return name.includes(needle) ? 1 : 2;
  };
  return items
    .filter((item) => (item.can_mention || item.can_add) && rank(item) < 2)
    .slice()
    .sort((left, right) => {
      const kindOrder = (left.kind === "user" ? 0 : 1) - (right.kind === "user" ? 0 : 1);
      return kindOrder || rank(left) - rank(right) || left.name.localeCompare(right.name);
    });
}

interface RoomMentionEditRange {
  start: number;
  previousEnd: number;
  nextEnd: number;
}

function validOffset(value: number, length: number): boolean {
  return Number.isInteger(value) && value >= 0 && value <= length;
}

/**
 * Resolve an edit from the pre-input selection when the changed text proves it.
 * Checking both unchanged sides handles replacements whose inserted length differs
 * from the selected text, including paste and composition commits.
 */
function rangeFromPreviousSelection(
  previous: string,
  next: string,
  hint: RoomMentionEditHint,
): RoomMentionEditRange | null {
  const selectionStart = hint.previousSelectionStart;
  const selectionEnd = hint.previousSelectionEnd;
  if (
    selectionStart === undefined ||
    selectionEnd === undefined ||
    !validOffset(selectionStart, previous.length) ||
    !validOffset(selectionEnd, previous.length) ||
    selectionEnd < selectionStart
  )
    return null;

  let start = selectionStart;
  let previousEnd = selectionEnd;
  if (start === previousEnd) {
    const inputType = hint.inputType?.toLowerCase() ?? "";
    if (inputType.endsWith("backward")) {
      start = hint.caret;
    } else if (inputType.endsWith("forward")) {
      previousEnd += previous.length - next.length;
    } else if (inputType.startsWith("delete")) {
      return null;
    }
  }
  const nextEnd = next.length - (previous.length - previousEnd);
  if (
    !validOffset(start, previous.length) ||
    !validOffset(previousEnd, previous.length) ||
    previousEnd < start ||
    !validOffset(nextEnd, next.length) ||
    hint.caret !== nextEnd ||
    hint.selectionEnd !== nextEnd ||
    previous.slice(0, start) !== next.slice(0, start) ||
    previous.slice(previousEnd) !== next.slice(nextEnd)
  )
    return null;
  return { start, previousEnd, nextEnd };
}

/**
 * Use the post-edit caret as a suffix boundary when the unchanged suffix proves
 * where a contiguous edit ended. Restricting the prefix search to that boundary
 * disambiguates repeated visible tokens without assuming the inserted text length.
 */
function rangeFromCaret(
  previous: string,
  next: string,
  hint: RoomMentionEditHint,
): RoomMentionEditRange | null {
  if (!validOffset(hint.caret, next.length) || hint.selectionEnd !== hint.caret) return null;
  const previousEnd = hint.caret + previous.length - next.length;
  if (
    !validOffset(previousEnd, previous.length) ||
    previous.slice(previousEnd) !== next.slice(hint.caret)
  )
    return null;
  const prefixLimit = Math.min(hint.caret, previousEnd);
  let start = 0;
  while (start < prefixLimit && previous[start] === next[start]) start++;
  return { start, previousEnd, nextEnd: hint.caret };
}

function mapMentionRange(
  next: string,
  mentions: readonly RoomDraftMention[],
  range: RoomMentionEditRange,
): RoomDraftMention[] {
  const delta = range.nextEnd - range.previousEnd;
  return mentions.flatMap((mention) => {
    let token = mention;
    if (mention.end <= range.start) {
      // The token is before the edit.
    } else if (mention.start >= range.previousEnd) {
      token = { ...mention, start: mention.start + delta, end: mention.end + delta };
    } else {
      return [];
    }
    return next.slice(token.start, token.end) === `@${token.name}` ? [token] : [];
  });
}

/**
 * When text alone admits several minimal edit ranges, retain only identities whose
 * offsets survive every possible alignment. This conservative fallback never moves
 * one duplicate name's identity onto another identical visible token.
 */
function mapUnambiguousTextDiff(
  previous: string,
  next: string,
  mentions: readonly RoomDraftMention[],
): RoomDraftMention[] {
  const delta = next.length - previous.length;
  let prefix = 0;
  while (prefix < previous.length && prefix < next.length && previous[prefix] === next[prefix])
    prefix++;
  let suffix = 0;
  while (
    suffix < previous.length &&
    suffix < next.length &&
    previous[previous.length - suffix - 1] === next[next.length - suffix - 1]
  )
    suffix++;

  const previousSuffixStart = previous.length - suffix;
  const width = Math.max(0, previousSuffixStart - prefix, -delta);
  const minStart = Math.max(0, previousSuffixStart - width);
  const maxStart = Math.min(prefix, previous.length - width, next.length - width - delta);
  if (minStart > maxStart) return [];

  return mentions.flatMap((mention) => {
    let token = mention;
    if (mention.end <= minStart) {
      // Its position is unchanged for every minimal alignment.
    } else if (mention.start >= maxStart + width) {
      token = { ...mention, start: mention.start + delta, end: mention.end + delta };
    } else {
      return [];
    }
    return next.slice(token.start, token.end) === `@${token.name}` ? [token] : [];
  });
}

/** Move exact token offsets across one edit; ambiguous identities are dropped safely. */
export function reconcileRoomMentionEdit(
  previous: string,
  next: string,
  mentions: readonly RoomDraftMention[],
  hint?: RoomMentionEditHint,
): RoomDraftMention[] {
  if (mentions.length === 0) return [];
  if (previous === next) {
    const selectionStart = hint?.previousSelectionStart;
    const selectionEnd = hint?.previousSelectionEnd;
    if (selectionStart === selectionEnd) return [...mentions];
    if (
      hint !== undefined &&
      selectionStart !== undefined &&
      selectionEnd !== undefined &&
      validOffset(selectionStart, previous.length) &&
      validOffset(selectionEnd, previous.length) &&
      selectionEnd >= selectionStart
    ) {
      const range = rangeFromPreviousSelection(previous, next, hint);
      if (range !== null) return mapMentionRange(next, mentions, range);
      return mentions.filter(
        (mention) => mention.end <= selectionStart || mention.start >= selectionEnd,
      );
    }
    return [...mentions];
  }
  if (hint !== undefined) {
    const range =
      rangeFromPreviousSelection(previous, next, hint) ?? rangeFromCaret(previous, next, hint);
    if (range !== null) return mapMentionRange(next, mentions, range);
  }
  return mapUnambiguousTextDiff(previous, next, mentions);
}

/** Replace the active `@query` with one identity-bound token and preserve other offsets. */
export function insertRoomMention(
  content: string,
  mentions: readonly RoomDraftMention[],
  query: RoomMentionQuery,
  participant: RoomParticipantRef & { name: string },
): { content: string; mentions: RoomDraftMention[]; caret: number } {
  const start = query.start;
  const end = start + query.query.length + 1;
  const token = `@${participant.name}`;
  const insertion = `${token} `;
  const suffix = content.slice(end).replace(/^ /, "");
  const next = content.slice(0, start) + insertion + suffix;
  const delta = insertion.length - (end - start) - (content.slice(end).length - suffix.length);
  const shifted = mentions.flatMap((mention) => {
    if (mention.end <= start) return [mention];
    if (mention.start >= end)
      return [{ ...mention, start: mention.start + delta, end: mention.end + delta }];
    return [];
  });
  shifted.push({
    kind: participant.kind,
    id: participant.id,
    name: participant.name,
    start,
    end: start + token.length,
  });
  shifted.sort((left, right) => left.start - right.start);
  return { content: next, mentions: shifted, caret: start + insertion.length };
}

/** Send each selected identity once, ordered by the visible token positions. */
export function roomMentionRefs(mentions: readonly RoomDraftMention[]): RoomParticipantRef[] {
  const seen = new Set<string>();
  return [...mentions]
    .sort((left, right) => left.start - right.start)
    .flatMap(({ kind, id }) => {
      const key = `${kind}:${id}`;
      if (seen.has(key)) return [];
      seen.add(key);
      return [{ kind, id }];
    });
}

export interface RoomMentionSegment {
  text: string;
  mention?: RoomMessageMention;
}

/** Match canonical mention metadata to the message's visible @tokens in metadata order. */
export function roomMentionSegments(
  text: string,
  mentions: readonly RoomMessageMention[],
): RoomMentionSegment[] {
  const segments: RoomMentionSegment[] = [];
  let cursor = 0;
  for (const mention of mentions) {
    const token = `@${mention.name}`;
    let start = text.indexOf(token, cursor);
    while (start >= 0) {
      const before = text[start - 1];
      const after = text[start + token.length];
      const boundaryBefore = start === 0 || /\s/.test(before ?? "");
      const boundaryAfter = after === undefined || !/[\p{L}\p{N}_]/u.test(after);
      if (boundaryBefore && boundaryAfter) break;
      start = text.indexOf(token, start + 1);
    }
    if (start < 0) continue;
    if (start > cursor) segments.push({ text: text.slice(cursor, start) });
    segments.push({ text: token, mention });
    cursor = start + token.length;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor) });
  return segments.length > 0 ? segments : text ? [{ text }] : [];
}
