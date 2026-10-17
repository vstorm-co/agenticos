import { describe, expect, it } from "vitest";

import type { Mentionable } from "@/types/mention";
import { readableLink, richSegments } from "./rich-text";

const NOTION: Mentionable = { kind: "mcp", id: "n", name: "Notion" };

describe("a message's rich runs", () => {
  it("cuts mentions first, then addresses, leaving sentence punctuation outside", () => {
    expect(richSegments("@Notion: read (https://a.io/x?y=1), then stop", [NOTION])).toEqual([
      { text: "@Notion", item: NOTION },
      { text: ": read (" },
      { text: "https://a.io/x?y=1", url: "https://a.io/x?y=1" },
      { text: "), then stop" },
    ]);
  });

  it("reads an address as its host and path", () => {
    expect(readableLink("https://www.youtube.com/")).toEqual({ host: "youtube.com", path: "" });
    expect(readableLink("https://a.io/x?y=1")).toEqual({ host: "a.io", path: "/x?y=1" });
    expect(readableLink("https://[bad")).toEqual({ host: "https://[bad", path: "" });
  });
});
