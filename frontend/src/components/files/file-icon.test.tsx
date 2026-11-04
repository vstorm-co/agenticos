import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FileIcon } from "./file-icon";

/** The rendered mark, which is what a reader actually sees. */
function mark(name: string, mimeType?: string): string {
  return render(<FileIcon name={name} mimeType={mimeType} />).container.innerHTML;
}

/**
 * One icon set.
 *
 * There were two - `FileKindIcon` over eleven preview kinds in `chat/`, and
 * `FileIcon` over six suffix groups in `sandboxes/` - so the same `.json` an agent
 * wrote drew a code mark beside a message and a code mark in the panel by
 * coincidence, and `.pdf` drew two different ones.
 *
 * Asserted on grouping and distinctness rather than on which lucide component came
 * back: the point is that a glance separates a picture from a spreadsheet, not that
 * the picture is that particular glyph.
 */
describe("marking a file by what it is", () => {
  it("tells the three media kinds apart", () => {
    expect(new Set([mark("a.png"), mark("a.mp3"), mark("a.mp4")]).size).toBe(3);
  });

  it("distinguishes source code, JSON data and markup", () => {
    expect(new Set([mark("script.py"), mark("data.json"), mark("page.html")]).size).toBe(3);
    expect(mark("a.py")).toBe(mark("a.ts"));
    expect(mark("a.JSON")).toBe(mark("a.json"));
    expect(mark("a.jsonl")).toBe(mark("a.json"));
    expect(mark("logo.svg")).toBe(mark("a.ts"));
  });

  it("marks both spreadsheet kinds as one", () => {
    expect(mark("a.csv")).toBe(mark("a.xlsx"));
    expect(mark("a.csv")).not.toBe(mark("a.ts"));
  });

  it("distinguishes PDF from text documents", () => {
    expect(mark("a.pdf")).not.toBe(mark("a.md"));
    expect(mark("a.md")).toBe(mark("a.docx"));
  });

  it("marks an archive as an archive", () => {
    expect(mark("a.zip")).not.toBe(mark("a.pdf"));
    expect(mark("a.zip")).not.toBe(mark("a.txt"));
  });

  it("distinguishes plain text from an unrecognized format", () => {
    expect(mark("a.txt")).not.toBe(mark("blob.bin"));
    expect(mark("a.txt")).not.toBe(mark("a.ts"));
  });

  it("reads a media type where the name has nothing to say", () => {
    // Which is every file with no extension, and every upload of a type the browser
    // did not recognise.
    expect(mark("Makefile", "image/png")).toBe(mark("a.png"));
  });

  it("hides the mark from a screen reader, since the name is beside it", () => {
    const { container } = render(<FileIcon name="a.png" />);

    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
