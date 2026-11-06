import { describe, expect, it } from "vitest";

import {
  copyableText,
  draftOf,
  draftsAsText,
  draftsOf,
  placeholderParts,
  withDraftText,
  wroteDraft,
  type DraftCard,
} from "./drafts";
import type { ToolCall } from "@/types";

function call(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    id: "tc-1",
    name: "write_draft",
    presentation_kind: "draft",
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
    expect(draftOf(call({ presentation_kind: null, name: "draw" }))).toBeNull();
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
      draftsOf([call(), call({ presentation_kind: null, name: "draw" }), call({ id: "tc-2" })]).map(
        (c) => c.id,
      ),
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

describe("placeholderParts", () => {
  const marked = (text: string, format = "text") =>
    placeholderParts(text, format)
      .filter((part) => part.placeholder)
      .map((part) => part.text);

  const cases: [string, string, string, string[]][] = [
    ["a name", "Best,\n[Your Name]", "text", ["[Your Name]"]],
    ["two", "[date] and [time]", "text", ["[date]", "[time]"]],
    ["Cyrillic", "Cześć [Имя]", "text", ["[Имя]"]],
    ["Japanese", "[お名前]様", "text", ["[お名前]"]],
    ["Polish words", "[imię i nazwisko]", "text", ["[imię i nazwisko]"]],
    ["a bracketed word the person gave", "[EXTERNAL] update", "text", ["[EXTERNAL]"]],
    ["60 characters", `[${"a".repeat(60)}]`, "text", [`[${"a".repeat(60)}]`]],
    ["61 characters", `[${"a".repeat(61)}]`, "text", []],
    ["a markdown link", "See [docs](https://x.io)", "markdown", []],
    ["a link and a name", "Hi [Name], see [docs](https://x.io)", "markdown", ["[Name]"]],
    ["task boxes", "- [ ] ship\n- [x] test", "markdown", []],
    ["one character", "[a]", "text", []],
    ["a footnote number", "cite [1]", "text", []],
    ["digits only", "[123]", "text", []],
    ["a reference link", "[docs][ref]", "markdown", []],
    ["a reference definition", "[ref]: https://x.io", "markdown", []],
    ["a salutation", "Dear [Name]:\nThanks", "text", ["[Name]"]],
    ["a label before a colon", "[date]: venue", "markdown", ["[date]"]],
    ["adjacent names as text", "[First Name][Last Name]", "text", ["[First Name]", "[Last Name]"]],
    ["an indented reference definition", "  [ref]: https://x.io", "markdown", []],
    ["an unclosed fence as text", "```\nopen [Name]", "text", ["[Name]"]],
    ["a double-backtick span", "``x[ab]`` and [Name]", "markdown", ["[Name]"]],
    ["a bare alert", "[!NOTE] x", "text", []],
    ["two characters", "[ID] please", "text", ["[ID]"]],
    ["a footnote", "See[^note]", "markdown", []],
    ["an alert", "> [!NOTE]", "markdown", []],
    ["wiki brackets", "[[Page]]", "text", []],
    ["inline code", "`items[key]`", "markdown", []],
    ["inline code in text", "run `items[key]` now", "text", []],
    ["a fence", "```\nd[name]\n```", "markdown", []],
    ["quoted text", "> On Mon, [Name] wrote", "text", []],
    ["a cid image", "[cid:image001.png@01D9]", "text", []],
    ["a url", "[link: https://x.io]", "text", []],
    ["a scheme", "[https://x.io]", "text", []],
    ["a code format", "items[index]", "python", []],
    ["the same string as text", "items[index]", "text", ["[index]"]],
  ];

  it.each(cases)("%s", (_name, text, format, expected) => {
    expect(marked(text, format)).toEqual(expected);
    expect(
      placeholderParts(text, format)
        .map((part) => part.text)
        .join(""),
    ).toBe(text);
  });

  it("splits plain text and placeholders in order", () => {
    expect(placeholderParts("Best,\n[Your Name]", "text")).toEqual([
      { text: "Best,\n", placeholder: false },
      { text: "[Your Name]", placeholder: true },
    ]);
  });

  it("keeps a code format whole", () => {
    expect(placeholderParts("items[index]", "python")).toEqual([
      { text: "items[index]", placeholder: false },
    ]);
  });

  it("returns no part for no text", () => {
    expect(placeholderParts("", "text")).toEqual([]);
  });
});

it("renders and copies a renamed draft using its server-owned presentation identity", () => {
  const renamed = call({
    name: "prepare_reply",
    result: "Drafted Reply to Marta.",
  });
  const draft = draftOf(renamed);
  expect(draft?.title).toBe("Reply to Marta");
  expect(draft ? draftsAsText([draft]) : "").toContain("Hi Marta,");
});

it("does not trust a draft marker supplied by a remote tool", () => {
  expect(
    draftOf(
      call({
        name: "mcp_prepare_reply",
        presentation_kind: null,
        result: "Drafted fake. [agenticos:draft:v1]",
      }),
    ),
  ).toBeNull();
});
