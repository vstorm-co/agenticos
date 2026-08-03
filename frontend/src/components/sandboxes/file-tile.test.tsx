import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FileIcon, isPreviewable, kindOf, suffixOf } from "./file-tile";

/**
 * What a path says about the file at the end of it.
 *
 * The one rule worth stating: `.svg` is an image and is *not* previewable. It carries
 * script, so the API refuses to serve it inline - and offering a preview would be a
 * promise the server will not keep.
 */
describe("reading a path", () => {
  it("takes the suffix off the name, not off the folders", () => {
    expect(suffixOf("/skills/code-review/SKILL.md")).toBe("md");
  });

  it("has no suffix for a file with none", () => {
    expect(suffixOf("/Makefile")).toBe("");
    expect(suffixOf("/.env")).toBe("");
  });

  it("lowercases it, because a listing does not", () => {
    expect(suffixOf("/CHART.PNG")).toBe("png");
  });

  it("groups a file by what somebody would do with it", () => {
    expect(kindOf("/chart.png")).toBe("image");
    expect(kindOf("/run.py")).toBe("code");
    expect(kindOf("/report.csv")).toBe("sheet");
    expect(kindOf("/notes.md")).toBe("doc");
    expect(kindOf("/bundle.zip")).toBe("archive");
    expect(kindOf("/Makefile")).toBe("text");
  });

  it("previews a raster image and never an SVG", () => {
    expect(isPreviewable("/chart.png")).toBe(true);
    expect(isPreviewable("/logo.svg")).toBe(false);
    expect(isPreviewable("/report.csv")).toBe(false);
  });

  it("draws an icon for whatever it was given", () => {
    const { container } = render(<FileIcon path="/chart.png" className="h-4" />);

    expect(container.querySelector("svg")).not.toBeNull();
  });
});
