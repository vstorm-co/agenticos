import { describe, expect, it } from "vitest";

import { DEFAULT_FORMAT, displayName, draftFromFilename, toFormat } from "./file-name";

/**
 * A context file's name and its format live in separate columns, and three
 * things read them: the renderer (which wants a filename), the format select
 * (which wants one of its own options), and a drop (which has a filename and
 * nothing else).
 */

describe("displayName", () => {
  it("composes the extension the renderer needs, which the name does not carry", () => {
    expect(displayName("glossary", "md")).toBe("glossary.md");
  });

  it("does not double an extension somebody typed into the name", () => {
    expect(displayName("notes.md", "md")).toBe("notes.md");
    expect(displayName("NOTES.MD", "md")).toBe("NOTES.MD");
  });

  it("leaves the name alone when there is no format to add", () => {
    expect(displayName("glossary", "  ")).toBe("glossary");
  });
});

describe("toFormat", () => {
  it("takes a value the catalog lists, however it was cased", () => {
    expect(toFormat("MD")).toBe("md");
    expect(toFormat(" csv ")).toBe("csv");
  });

  it("maps the spellings people write for the same thing", () => {
    expect(toFormat("markdown")).toBe("md");
    expect(toFormat("yml")).toBe("yaml");
    expect(toFormat("text")).toBe("txt");
  });

  it("falls back to the default rather than to a blank control", () => {
    expect(toFormat("docx")).toBe(DEFAULT_FORMAT);
    expect(toFormat("")).toBe(DEFAULT_FORMAT);
  });
});

describe("draftFromFilename", () => {
  it("splits the extension off as the format, because the name does not hold it", () => {
    expect(draftFromFilename("refund-policy.md")).toEqual({ name: "refund-policy", format: "md" });
  });

  it("makes a handle out of a title, since the name is what a tool call quotes", () => {
    expect(draftFromFilename("Refund Policy.TXT")).toEqual({
      name: "refund-policy",
      format: "txt",
    });
  });

  it("keeps the whole name of a file with no extension", () => {
    expect(draftFromFilename("README")).toEqual({ name: "readme", format: DEFAULT_FORMAT });
  });

  it("keeps a leading-dot name whole rather than reading it as an extension", () => {
    expect(draftFromFilename(".env")).toEqual({ name: ".env", format: DEFAULT_FORMAT });
  });

  it("truncates to what the name column accepts", () => {
    expect(draftFromFilename(`${"a".repeat(80)}.md`).name).toHaveLength(64);
  });
});
