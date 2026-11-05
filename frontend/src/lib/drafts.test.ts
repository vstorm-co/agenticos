import { describe, expect, it } from "vitest";

import {
  copyableText,
  draftOf,
  draftsAsText,
  draftsOf,
  withDraftText,
  wroteDraft,
  type DraftCard,
} from "./drafts";
import type { ToolCall } from "@/types";

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "tc-1",
    name: "write_draft",
    status: "completed",
    result: "Drafted Reply to Marta.",
    args: {
      title: "Reply to Marta",
      kind: "email",
      versions: [
        {
          fields: [
            { name: "Subject", text: "Re: Q4 deck" },
            { name: "Body", text: "Hi Marta,", format: "markdown" },
          ],
        },
      ],
    },
    ...overrides,
  };
}

function card(overrides: Partial<DraftCard> = {}): DraftCard {
  return {
    id: "tc-1",
    title: "Reply",
    kind: "email",
    versions: [
      {
        label: null,
        fields: [
          { name: "Subject", text: "Re: Q4 deck", format: "text" },
          { name: "Body", text: "\nHi Marta,\n\n", format: "text" },
        ],
      },
    ],
    ...overrides,
  };
}

describe("draftOf", () => {
  it("reads the card from a completed call", () => {
    expect(draftOf(call())).toEqual({
      id: "tc-1",
      title: "Reply to Marta",
      kind: "email",
      versions: [
        {
          label: null,
          fields: [
            { name: "Subject", text: "Re: Q4 deck", format: "text" },
            { name: "Body", text: "Hi Marta,", format: "markdown" },
          ],
        },
      ],
    });
  });

  it("draws nothing for a call still running", () => {
    expect(draftOf(call({ status: "running" }))).toBeNull();
  });

  it("draws nothing for a last attempt's refusal stored as the result", () => {
    expect(draftOf(call({ result: "Each version needs a label..." }))).toBeNull();
    expect(wroteDraft(undefined)).toBe(false);
  });

  it("draws nothing for another tool", () => {
    expect(draftOf(call({ name: "draw" }))).toBeNull();
  });

  it("draws nothing when the arguments no longer parse", () => {
    expect(draftOf(call({ args: { title: "x" } }))).toBeNull();
    expect(draftOf(call({ args: { title: "x", kind: "email", versions: [] } }))).toBeNull();
    expect(draftOf(call({ args: { title: "x", kind: "email", versions: ["no"] } }))).toBeNull();
    expect(
      draftOf(call({ args: { title: "x", kind: "email", versions: [{ fields: [] }] } })),
    ).toBeNull();
    expect(
      draftOf(
        call({ args: { title: "x", kind: "email", versions: [{ fields: [{ name: "a" }] }] } }),
      ),
    ).toBeNull();
    expect(
      draftOf(call({ args: { title: "x", kind: "email", versions: [{ fields: [null] }] } })),
    ).toBeNull();
  });

  it("keeps a version's label", () => {
    const labelled = call({
      args: { title: "t", kind: "k", versions: [{ label: "Short", fields: [{ text: "a" }] }] },
    });
    expect(draftOf(labelled)?.versions[0]).toEqual({
      label: "Short",
      fields: [{ name: null, text: "a", format: "text" }],
    });
  });

  it("reads a blank field name as none", () => {
    const blank = call({
      args: {
        title: "t",
        kind: "k",
        versions: [
          {
            fields: [
              { name: "", text: "a" },
              { name: "  ", text: "b" },
            ],
          },
        ],
      },
    });
    expect(draftOf(blank)?.versions[0]?.fields.map((f) => f.name)).toEqual([null, null]);
  });

  it("collects the cards of a list of calls, skipping the rest", () => {
    expect(
      draftsOf([call(), call({ name: "draw" }), call({ id: "tc-2" })]).map((c) => c.id),
    ).toEqual(["tc-1", "tc-2"]);
  });
});

describe("copyableText", () => {
  it("trims the blank lines around a text and nothing else", () => {
    expect(copyableText("\n\n  Hi Marta,\n\nBest\n\n")).toBe("  Hi Marta,\n\nBest");
  });
});

describe("draftsAsText", () => {
  it("writes a field's name above its text", () => {
    expect(draftsAsText([card()])).toBe("Subject\nRe: Q4 deck\n\nBody\nHi Marta,");
  });

  it("leads each version with its label when there are several", () => {
    const versions = [
      { label: "Short", fields: [{ name: null, text: "Hi", format: "text" }] },
      { label: "Long", fields: [{ name: null, text: "Hello there", format: "text" }] },
    ];
    expect(draftsAsText([card({ versions })])).toBe("Short\n\nHi\n\nLong\n\nHello there");
  });

  it("separates cards by a blank line", () => {
    const one = card({
      versions: [{ label: null, fields: [{ name: null, text: "a", format: "text" }] }],
    });
    expect(draftsAsText([one, one])).toBe("a\n\na");
  });
});

describe("withDraftText", () => {
  it("returns the content alone when there are no drafts", () => {
    expect(withDraftText("Here you go.", [])).toBe("Here you go.");
  });

  it("returns the drafts alone when there is no content", () => {
    expect(withDraftText(undefined, [card()])).toBe(draftsAsText([card()]));
  });

  it("joins the two by a blank line", () => {
    expect(withDraftText("Here you go.", [card()])).toBe(
      `Here you go.\n\n${draftsAsText([card()])}`,
    );
  });
});
