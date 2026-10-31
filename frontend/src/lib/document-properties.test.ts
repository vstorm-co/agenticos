import { describe, expect, it } from "vitest";
import { documentProperties, withDocumentBody, withDocumentProperty } from "./document-properties";

describe("document properties", () => {
  it("preserves header bytes, comments, nested data and line endings on body edits", () => {
    const header = "---\r\n# Kept\r\nstatus: draft\r\ntags: [a, b]\r\n---\r\n";
    expect(withDocumentBody(header + "Old", "New\n")).toBe(header + "New\n");
    expect(withDocumentBody("Plain", "New")).toBe("New");
  });
  it("changes string properties without losing nested values or the body", () => {
    const source = "---\nstatus: draft\nnested: {count: 2}\n---\n# Body\n";
    const next = withDocumentProperty(source, "status", "approved");
    expect(documentProperties(next).document.get("status")).toBe("approved");
    expect(documentProperties(next).document.getIn(["nested", "count"])).toBe(2);
    expect(next.endsWith("# Body\n")).toBe(true);
    expect(
      documentProperties(withDocumentProperty(next, "status", null)).document.has("status"),
    ).toBe(false);
  });
  it("adds the first property and keeps system properties outside user control", () => {
    expect(
      documentProperties(withDocumentProperty("# Body", "owner", "Sam")).document.get("owner"),
    ).toBe("Sam");
    expect(withDocumentProperty("# Body", "created_at", "spoofed")).toBe("# Body");
    expect(
      documentProperties("---\ncreated_at: spoofed\nowner: Sam\n---\n").fields.map((f) => f.key),
    ).toEqual(["owner"]);
  });
  it("preserves invalid and non-mapping legacy frontmatter rather than dropping it", () => {
    for (const header of ["broken: [", "- item", "same: a\nsame: b"]) {
      const source = `---\n${header}\n---\nBody`;
      expect(documentProperties(source).valid).toBe(false);
      expect(withDocumentProperty(source, "status", "draft")).toBe(source);
      expect(withDocumentBody(source, "Changed")).toBe(`---\n${header}\n---\nChanged`);
    }
  });
  it("does not expand aliases or convert typed imported properties into strings", () => {
    const props = documentProperties("---\ncount: 2\nlist: &x [a]\nalias: *x\n---\n");
    expect(props.fields.every((f) => !f.editable)).toBe(true);
  });
});
