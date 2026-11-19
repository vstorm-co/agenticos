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

  it("deleting one duplicate token removes only its identity", () => {
    const mentions = [
      { kind: "user" as const, id: "user-1", name: "Alex", start: 4, end: 9 },
      { kind: "agent" as const, id: "agent-1", name: "Alex", start: 10, end: 15 },
    ];
    const previous = "Ask @Alex @Alex ";
    const next = previous.slice(0, 4) + previous.slice(10);
    const reconciled = reconcileRoomMentionEdit(previous, next, mentions);

    expect(next).toBe("Ask @Alex ");
    expect(reconciled).toEqual([{ kind: "agent", id: "agent-1", name: "Alex", start: 4, end: 9 }]);
    expect(roomMentionRefs(reconciled)).toEqual([{ kind: "agent", id: "agent-1" }]);
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
