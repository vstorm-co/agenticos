import { describe, expect, it } from "vitest";
import { markdownDocument } from "./markdown-document";

describe("Markdown documents", () => {
  it("separates frontmatter while preserving Unicode and original line endings", () => {
    expect(markdownDocument("---\r\ntitle: Zażółć\r\n---\r\n# Note\r\n")).toEqual({
      frontmatter: "title: Zażółć\r\n",
      body: "# Note\r\n",
    });
    expect(markdownDocument("\uFEFF---\ntags: [a, b]\n...\nBody")).toEqual({
      frontmatter: "tags: [a, b]\n",
      body: "Body",
    });
  });
  it("supports empty frontmatter and a document with only frontmatter", () => {
    expect(markdownDocument("---\n---\nBody")).toEqual({ frontmatter: "", body: "Body" });
    expect(markdownDocument("---\ntitle: Note\n---")).toEqual({
      frontmatter: "title: Note\n",
      body: "",
    });
  });
  it.each(["# Note\n---\ntext\n---", "---\nunclosed: [", "# Normal\n\n---\n", ""])(
    "leaves incomplete or non-leading blocks in the body: %s",
    (source) => {
      expect(markdownDocument(source)).toEqual({ frontmatter: null, body: source });
    },
  );
});
