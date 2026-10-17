import { describe, expect, it } from "vitest";

import type { Mentionable } from "@/types/mention";
import { insertMention, matching, mentionSegments, stillMentioned } from "./mentions";

const NOTION: Mentionable = { kind: "mcp", id: "n", name: "Notion" };
const NOTION_WORK: Mentionable = { kind: "mcp", id: "nw", name: "Notion Work" };
const SEARCH: Mentionable = { kind: "capability", id: "web_research", name: "Web research" };

describe("a mention in the text", () => {
  it("replaces the typed query with the token and one space, wherever the caret was", () => {
    expect(insertMention("ask @no about it", { start: 4, query: "no" }, NOTION)).toEqual({
      text: "ask @Notion about it",
      caret: 12,
    });
  });

  it("cuts the text at each token, the longest name first and only as a whole word", () => {
    expect(
      mentionSegments("@Notion Work, then @Notion. Not @Notional or mail@Notion", [
        NOTION,
        NOTION_WORK,
      ]),
    ).toEqual([
      { text: "@Notion Work", item: NOTION_WORK },
      { text: ", then " },
      { text: "@Notion", item: NOTION },
      { text: ". Not @Notional or mail@Notion" },
    ]);
    expect(mentionSegments("plain", [])).toEqual([{ text: "plain" }]);
    expect(mentionSegments("", [])).toEqual([]);
  });

  it("keeps only what the text still names", () => {
    expect(stillMentioned("use @Notion", [NOTION, SEARCH])).toEqual([NOTION]);
  });

  it("matches however the name is typed", () => {
    expect(matching([NOTION, SEARCH], "webres")).toEqual([SEARCH]);
  });
});
