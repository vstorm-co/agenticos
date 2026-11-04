import { describe, expect, it } from "vitest";
import { withDocumentBody } from "./document-properties";

describe("document properties", () => {
  it("preserves header bytes, comments, nested data and line endings on body edits", () => {
    const header = "---\r\n# Kept\r\nstatus: draft\r\ntags: [a, b]\r\n---\r\n";
    expect(withDocumentBody(header + "Old", "New\n")).toBe(header + "New\n");
    expect(withDocumentBody("Plain", "New")).toBe("New");
  });
  it("preserves invalid and non-mapping legacy frontmatter rather than dropping it", () => {
    for (const header of ["broken: [", "- item", "same: a\nsame: b"]) {
      const source = `---\n${header}\n---\nBody`;
      expect(withDocumentBody(source, "Changed")).toBe(`---\n${header}\n---\nChanged`);
    }
  });
});
