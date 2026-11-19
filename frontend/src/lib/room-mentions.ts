import type { RoomMessageMention } from "@/types/conversation";
import type { RoomDraftMention, RoomParticipantRead, RoomParticipantRef } from "@/types/room";

export interface RoomMentionQuery {
  start: number;
  query: string;
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

/** Move exact token offsets across one edit; an edit touching a token unpicks only it. */
export function reconcileRoomMentionEdit(
  previous: string,
  next: string,
  mentions: readonly RoomDraftMention[],
): RoomDraftMention[] {
  if (previous === next || mentions.length === 0) return [...mentions];
  let start = 0;
  while (start < previous.length && start < next.length && previous[start] === next[start]) start++;
  let previousEnd = previous.length;
  let nextEnd = next.length;
  while (
    previousEnd > start &&
    nextEnd > start &&
    previous[previousEnd - 1] === next[nextEnd - 1]
  ) {
    previousEnd--;
    nextEnd--;
  }
  const delta = nextEnd - previousEnd;
  return mentions.flatMap((mention) => {
    let token = mention;
    if (start === previousEnd) {
      if (start <= mention.start)
        token = { ...mention, start: mention.start + delta, end: mention.end + delta };
      else if (start < mention.end) return [];
    } else if (previousEnd <= mention.start) {
      token = { ...mention, start: mention.start + delta, end: mention.end + delta };
    } else if (start < mention.end && previousEnd > mention.start) {
      return [];
    }
    return next.slice(token.start, token.end) === `@${token.name}` ? [token] : [];
  });
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
