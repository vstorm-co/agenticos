import { describe, expect, it } from "vitest";

import {
  insertRoomMention,
  matchingRoomMentionables,
  reconcileRoomMentionEdit,
  roomMentionAt,
  roomMentionRefs,
  roomMentionSegments,
  type RoomMentionEditHint,
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

const mention = (
  id: string,
  name: string,
  start: number,
  end: number,
  kind: "user" | "agent" = "user",
) => ({ kind, id, name, start, end });

describe("roomMentionAt", () => {
  it("finds the active @query and refuses ranges and non-mentions", () => {
    expect(roomMentionAt("hi @al", 6)).toEqual({ start: 3, query: "al" });
    expect(roomMentionAt("hi @al", 6, 6)).toEqual({ start: 3, query: "al" });
    expect(roomMentionAt("hi @al", 6, 5)).toBeNull();
    expect(roomMentionAt("mail@al", 7)).toBeNull();
  });
});

describe("matchingRoomMentionables ranking", () => {
  it("offers mentionable or addable people ordered by kind, match quality then name", () => {
    const addOnly = { ...person("user", "u4", "Zalex"), can_mention: false, can_add: true };
    const hidden = { ...person("user", "u5", "Alexa"), can_mention: false, can_add: false };
    const noMatch = person("user", "u6", "Bob");
    const items = [
      person("agent", "a1", "Alexis"),
      person("user", "u1", "Xalex"),
      person("user", "u2", "Alexander"),
      person("user", "u3", "Alex"),
      addOnly,
      hidden,
      noMatch,
    ];

    expect(matchingRoomMentionables(items, "Al-ex").map((item) => item.id)).toEqual([
      "u3",
      "u2",
      "u1",
      "u4",
      "a1",
    ]);
  });
});

describe("reconcileRoomMentionEdit with selection hints", () => {
  const hint = (over: Partial<RoomMentionEditHint>): RoomMentionEditHint => ({
    caret: 0,
    selectionEnd: 0,
    ...over,
  });

  it("returns nothing without mentions", () => {
    expect(reconcileRoomMentionEdit("a", "ab", [])).toEqual([]);
  });

  it("keeps every mention when identical text had a collapsed or unusable selection", () => {
    const mentions = [mention("u1", "Alex", 0, 5)];
    expect(reconcileRoomMentionEdit("@Alex", "@Alex", mentions)).toEqual(mentions);
    expect(
      reconcileRoomMentionEdit(
        "@Alex",
        "@Alex",
        mentions,
        hint({ previousSelectionStart: 2, previousSelectionEnd: 2 }),
      ),
    ).toEqual(mentions);
    expect(
      reconcileRoomMentionEdit("@Alex", "@Alex", mentions, hint({ previousSelectionStart: 1 })),
    ).toEqual(mentions);
    expect(
      reconcileRoomMentionEdit(
        "@Alex",
        "@Alex",
        mentions,
        hint({ previousSelectionStart: 9, previousSelectionEnd: 12 }),
      ),
    ).toEqual(mentions);
    expect(
      reconcileRoomMentionEdit(
        "@Alex",
        "@Alex",
        mentions,
        hint({ previousSelectionStart: 3, previousSelectionEnd: 1 }),
      ),
    ).toEqual(mentions);
  });

  it("maps same-text replacements around a validated selection", () => {
    const previous = "@Bob @Alex";
    const mentions = [mention("b", "Bob", 0, 4), mention("a", "Alex", 5, 10)];
    expect(
      reconcileRoomMentionEdit(
        previous,
        previous,
        mentions,
        hint({ caret: 10, selectionEnd: 10, previousSelectionStart: 5, previousSelectionEnd: 10 }),
      ),
    ).toEqual([mentions[0]]);
    expect(
      reconcileRoomMentionEdit(
        previous,
        previous,
        mentions,
        hint({ caret: 4, selectionEnd: 4, previousSelectionStart: 0, previousSelectionEnd: 4 }),
      ),
    ).toEqual([mentions[1]]);
  });

  it("keeps only mentions outside an unvalidated same-text selection", () => {
    const previous = "@Bob @Alex";
    const mentions = [mention("b", "Bob", 0, 4), mention("a", "Alex", 5, 10)];
    expect(
      reconcileRoomMentionEdit(
        previous,
        previous,
        mentions,
        hint({ caret: 3, selectionEnd: 3, previousSelectionStart: 5, previousSelectionEnd: 10 }),
      ),
    ).toEqual([mentions[0]]);
    expect(
      reconcileRoomMentionEdit(
        previous,
        previous,
        mentions,
        hint({ caret: 3, selectionEnd: 3, previousSelectionStart: 0, previousSelectionEnd: 4 }),
      ),
    ).toEqual([mentions[1]]);
  });

  it("shifts later mentions after a forward delete", () => {
    const mentions = [mention("b", "Bob", 0, 4), mention("a", "Alex", 7, 12)];
    expect(
      reconcileRoomMentionEdit(
        "@Bob x @Alex",
        "@Bob  @Alex",
        mentions,
        hint({
          caret: 5,
          selectionEnd: 5,
          previousSelectionStart: 5,
          previousSelectionEnd: 5,
          inputType: "deleteContentForward",
        }),
      ),
    ).toEqual([mention("b", "Bob", 0, 4), mention("a", "Alex", 6, 11)]);
  });

  it("drops a mention that a backward delete shortens", () => {
    expect(
      reconcileRoomMentionEdit(
        "Hi @Alex",
        "Hi @Ale",
        [mention("a", "Alex", 3, 8)],
        hint({
          caret: 7,
          selectionEnd: 7,
          previousSelectionStart: 8,
          previousSelectionEnd: 8,
          inputType: "deleteContentBackward",
        }),
      ),
    ).toEqual([]);
  });

  it("treats a collapsed typing edit as an insertion and drops stale token text", () => {
    const typing = hint({
      caret: 5,
      selectionEnd: 5,
      previousSelectionStart: 4,
      previousSelectionEnd: 4,
      inputType: "insertText",
    });
    expect(reconcileRoomMentionEdit("@Bob", "@Bob!", [mention("b", "Bob", 0, 4)], typing)).toEqual([
      mention("b", "Bob", 0, 4),
    ]);
    expect(
      reconcileRoomMentionEdit("@Bob", "@Bob!", [mention("z", "Zed", 0, 4)], {
        ...typing,
        inputType: undefined,
      }),
    ).toEqual([]);
  });

  it("falls back when the previous selection does not prove the edit", () => {
    const mentions = [mention("b", "Bob", 0, 4)];
    const sel = (start: number, end: number, caret: number, inputType?: string) =>
      hint({
        caret,
        selectionEnd: caret,
        previousSelectionStart: start,
        previousSelectionEnd: end,
        inputType,
      });
    const cases: Array<[string, string, RoomMentionEditHint]> = [
      ["@Bob xy", "@Bob y", sel(5, 5, 5, "deleteByCut")],
      ["@Bob", "@Bob!", sel(9, 9, 5)],
      ["@Bob", "@Bob!", sel(4, 9, 5)],
      ["@Bob", "@Bob!", sel(4, 2, 5)],
      ["@Bob", "@Bob!", hint({ caret: 5, selectionEnd: 5, previousSelectionStart: 4 })],
      ["@Bob", "@Bob!", sel(4, 4, 7, "deleteContentBackward")],
      ["abc", "abcd", sel(1, 1, 2, "deleteContentBackward")],
      ["abcdef", "a", sel(0, 0, 1, "insertText")],
      ["@Bob", "@Bob!", sel(4, 4, 4, "insertText")],
      ["abc", "xbc", sel(1, 1, 1, "insertText")],
      ["abc", "abx", sel(2, 2, 2, "insertText")],
    ];
    for (const [previous, next, over] of cases) {
      expect(reconcileRoomMentionEdit(previous, next, mentions, over)).toBeInstanceOf(Array);
    }
  });

  it("uses the caret as the suffix boundary when there is no previous selection", () => {
    const mentions = [mention("b", "Bob", 0, 4), mention("a", "Alex", 7, 12)];
    expect(
      reconcileRoomMentionEdit(
        "@Bob x @Alex",
        "@Bob @Alex",
        mentions,
        hint({ caret: 5, selectionEnd: 5 }),
      ),
    ).toEqual([mention("b", "Bob", 0, 4), mention("a", "Alex", 5, 10)]);
  });

  it("falls back to the text diff when the caret cannot prove the edit", () => {
    const mentions = [mention("b", "Bob", 0, 4)];
    const cases: Array<Partial<RoomMentionEditHint>> = [
      { caret: 99, selectionEnd: 99 },
      { caret: 5, selectionEnd: 4 },
      { caret: 0, selectionEnd: 0 },
    ];
    for (const over of cases) {
      expect(
        reconcileRoomMentionEdit("@Bob", "@Bob!", mentions, {
          caret: 0,
          selectionEnd: 0,
          ...over,
        }),
      ).toEqual(mentions);
    }
  });

  it("moves mentions that follow a text-only insertion and keeps ones before it", () => {
    const mentions = [mention("b", "Bob", 0, 4), mention("a", "Alex", 5, 10)];
    expect(reconcileRoomMentionEdit("@Bob @Alex", "@Bob, hi @Alex", mentions)).toEqual([
      mention("b", "Bob", 0, 4),
      mention("a", "Alex", 9, 14),
    ]);
  });
});

describe("insertRoomMention", () => {
  it("replaces the query, keeps mentions before, shifts those after and drops overlaps", () => {
    const result = insertRoomMention(
      "@Ann @al @Cy",
      [mention("ann", "Ann", 0, 4), mention("stale", "al", 6, 8), mention("cy", "Cy", 9, 12)],
      { start: 5, query: "al" },
      { kind: "agent", id: "al1", name: "Alice" },
    );

    expect(result.content).toBe("@Ann @Alice @Cy");
    expect(result.caret).toBe(12);
    expect(result.mentions.map(({ id, start, end }) => ({ id, start, end }))).toEqual([
      { id: "ann", start: 0, end: 4 },
      { id: "al1", start: 5, end: 11 },
      { id: "cy", start: 12, end: 15 },
    ]);
  });
});

describe("roomMentionRefs and segments", () => {
  it("sends each identity once", () => {
    expect(
      roomMentionRefs([
        mention("u1", "Alex", 10, 15),
        mention("u1", "Alex", 0, 5),
        mention("a1", "Alex", 6, 9, "agent"),
      ]),
    ).toEqual([
      { kind: "user", id: "u1" },
      { kind: "agent", id: "a1" },
    ]);
  });

  it("skips tokens without word boundaries and splits surrounding text", () => {
    const alex = { kind: "user" as const, id: "u1", name: "Alex" };
    expect(roomMentionSegments("@Alexander and @Alex ok", [alex])).toEqual([
      { text: "@Alexander and " },
      { text: "@Alex", mention: alex },
      { text: " ok" },
    ]);
    expect(roomMentionSegments("x@Alex", [alex])).toEqual([{ text: "x@Alex" }]);
    expect(roomMentionSegments("@Alex", [alex])).toEqual([{ text: "@Alex", mention: alex }]);
    expect(roomMentionSegments("", [alex])).toEqual([]);
    expect(roomMentionSegments("plain", [])).toEqual([{ text: "plain" }]);
  });
});
