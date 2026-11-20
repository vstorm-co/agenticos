import { describe, expect, it } from "vitest";

import {
  insertRoomMention,
  matchingRoomMentionables,
  reconcileRoomMentionEdit,
  roomMentionRefs,
  roomMentionSegments,
} from "./room-mentions";
import type { RoomParticipantRead } from "@/types/room";

function person(kind: "user" | "agent", id: string, name: string): RoomParticipantRead {
  return {
    kind,
    id,
    name,
    avatar_url: null,
    is_member: true,
    can_add: false,
    can_mention: true,
    auto_reply: false,
  };
}

describe("room mention identities", () => {
  it("keeps duplicate names as separate selectable people and agents", () => {
    const matches = matchingRoomMentionables(
      [person("user", "user-1", "Alex"), person("agent", "agent-1", "Alex")],
      "alex",
    );

    expect(matches.map(({ kind, id }) => ({ kind, id }))).toEqual([
      { kind: "user", id: "user-1" },
      { kind: "agent", id: "agent-1" },
    ]);
  });

  it("keeps two identical visible tokens tied to the identities picked for each", () => {
    const first = person("user", "user-1", "Alex");
    const second = person("agent", "agent-1", "Alex");
    const one = insertRoomMention("Ask @Alex @", [], { start: 4, query: "Alex" }, first);
    const two = insertRoomMention(one.content, one.mentions, { start: 10, query: "" }, second);

    expect(two.content).toBe("Ask @Alex @Alex ");
    expect(two.mentions.map(({ kind, id, start, end }) => ({ kind, id, start, end }))).toEqual([
      { kind: "user", id: "user-1", start: 4, end: 9 },
      { kind: "agent", id: "agent-1", start: 10, end: 15 },
    ]);
    expect(roomMentionRefs(two.mentions)).toEqual([
      { kind: "user", id: "user-1" },
      { kind: "agent", id: "agent-1" },
    ]);
    expect(
      roomMentionSegments("Ask @Alex @Alex", [
        { kind: "user", id: "user-1", name: "Alex" },
        { kind: "agent", id: "agent-1", name: "Alex" },
      ]).flatMap((segment) => (segment.mention ? [segment.mention.id] : [])),
    ).toEqual(["user-1", "agent-1"]);
  });

  it.each([
    ["first", 4, 10, 4, "agent", "agent-1"],
    ["second", 10, 16, 10, "user", "user-1"],
  ] as const)(
    "deleting the %s duplicate token removes only its identity",
    (_position, start, end, caret, remainingKind, remainingId) => {
      const mentions = [
        { kind: "user" as const, id: "user-1", name: "Alex", start: 4, end: 9 },
        { kind: "agent" as const, id: "agent-1", name: "Alex", start: 10, end: 15 },
      ];
      const previous = "Ask @Alex @Alex ";
      const next = previous.slice(0, start) + previous.slice(end);
      const reconciled = reconcileRoomMentionEdit(previous, next, mentions, {
        caret,
        selectionEnd: caret,
        previousSelectionStart: start,
        previousSelectionEnd: end,
        inputType: "deleteByCut",
      });
      const reconciledFromCaret = reconcileRoomMentionEdit(previous, next, mentions, {
        caret,
        selectionEnd: caret,
      });

      expect(next).toBe("Ask @Alex ");
      expect(reconciled).toEqual([
        { kind: remainingKind, id: remainingId, name: "Alex", start: 4, end: 9 },
      ]);
      expect(reconciledFromCaret).toEqual(reconciled);
      expect(roomMentionRefs(reconciled)).toEqual([{ kind: remainingKind, id: remainingId }]);
    },
  );

  it("drops duplicate identities when a text-only edit cannot identify which token survived", () => {
    const mentions = [
      { kind: "user" as const, id: "user-1", name: "Alex", start: 4, end: 9 },
      { kind: "agent" as const, id: "agent-1", name: "Alex", start: 10, end: 15 },
    ];
    const previous = "Ask @Alex @Alex ";
    const next = previous.slice(0, 4) + previous.slice(10);

    expect(reconcileRoomMentionEdit(previous, next, mentions)).toEqual([]);
  });

  it("does not retain a selected identity when pasted text replaces its token with the same text", () => {
    const previous = "Ask @Alex";
    const mention = { kind: "user" as const, id: "user-1", name: "Alex", start: 4, end: 9 };

    expect(
      reconcileRoomMentionEdit(previous, previous, [mention], {
        caret: 9,
        selectionEnd: 9,
        previousSelectionStart: 4,
        previousSelectionEnd: 9,
        inputType: "insertFromPaste",
      }),
    ).toEqual([]);
  });

  it("drops an overlapping identity when same-text replacement metadata cannot be validated", () => {
    const previous = "Ask @Alex";
    const mention = { kind: "user" as const, id: "user-1", name: "Alex", start: 4, end: 9 };

    expect(
      reconcileRoomMentionEdit(previous, previous, [mention], {
        caret: 8,
        selectionEnd: 8,
        previousSelectionStart: 4,
        previousSelectionEnd: 9,
        inputType: "insertFromPaste",
      }),
    ).toEqual([]);
  });

  it("keeps a mention identity when pasted text is inserted before its token", () => {
    const previous = "Hey @Alex";
    const next = "Copied text Hey @Alex";
    const reconciled = reconcileRoomMentionEdit(previous, next, [
      { kind: "user", id: "user-1", name: "Alex", start: 4, end: 9 },
    ]);

    expect(reconciled).toEqual([{ kind: "user", id: "user-1", name: "Alex", start: 16, end: 21 }]);
  });

  it("drops a mention identity when paste replaces the token text", () => {
    const reconciled = reconcileRoomMentionEdit("Hey @Alex", "Hey @Team", [
      { kind: "user", id: "user-1", name: "Alex", start: 4, end: 9 },
    ]);

    expect(reconciled).toEqual([]);
  });
});
