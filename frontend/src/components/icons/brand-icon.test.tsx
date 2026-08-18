import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BRAND_GLYPHS, PROVIDER_GLYPHS } from "@/lib/brand-glyphs.generated";

import { BrandIcon, brandMark, connectorBrand, isBrandName } from "./brand-icon";

const BRAND_NAMES = Object.keys(BRAND_GLYPHS) as (keyof typeof BRAND_GLYPHS)[];

/**
 * The checked-in glyph set, in place of two npm icon catalogues.
 *
 * A missing brand mark is the failure nothing else catches: the page renders,
 * the row is there, and the logo is simply absent - so what is asserted here is
 * that *every* name in the set draws something, not that a sampled one does.
 */
describe("the brand glyph set", () => {
  it.each(BRAND_NAMES)("draws %s", (name) => {
    const { container } = render(<BrandIcon name={name} />);
    const paths = container.querySelectorAll("svg path");

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) expect(path.getAttribute("d")).toBeTruthy();
  });

  it("draws every mark in currentColor, never in a brand palette", () => {
    // A mark that arrived with a literal fill would keep it through a theme
    // switch and read as a foreign element in a column of ink. The generator
    // refuses one at the source; this is the same invariant on what it wrote.
    for (const glyph of [...Object.values(BRAND_GLYPHS), ...Object.values(PROVIDER_GLYPHS)]) {
      expect(glyph.paths.some((path) => path.d.includes("#"))).toBe(false);
    }
  });

  it("keeps a source viewBox rather than assuming 24×24", () => {
    // Simple Icons are 24×24; Font Awesome's are not. Forcing one viewBox onto
    // both crops AWS to its top-left corner - which still renders, and is still
    // wrong.
    expect(BRAND_GLYPHS.notion.viewBox).toBe("0 0 24 24");
    expect(BRAND_GLYPHS.aws.viewBox).not.toBe("0 0 24 24");
  });
});

describe("BrandIcon", () => {
  it("stays out of the accessibility tree unless the caller names it", () => {
    const { container } = render(<BrandIcon name="slack" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  it("becomes an image with a name when the caller gives it one", () => {
    // An icon-only button has nothing else to announce, so the label is the
    // whole of what a screen reader gets.
    const { getByRole } = render(<BrandIcon name="slack" aria-label="Slack" />);
    expect(getByRole("img", { name: "Slack" })).toBeInTheDocument();
  });

  it("passes svg props through to the element", () => {
    const { container } = render(<BrandIcon name="github" className="h-4 w-4" />);
    expect(container.firstElementChild).toHaveClass("h-4", "w-4");
  });
});

describe("brandMark", () => {
  it("binds one mark so a table can hold it beside a lucide icon", () => {
    const Mark = brandMark("telegram");
    const { container } = render(<Mark className="h-3.5 w-3.5" aria-hidden />);

    expect(container.querySelector("svg")).toHaveClass("h-3.5", "w-3.5");
    expect(container.querySelector("svg path")?.getAttribute("d")).toBe(
      BRAND_GLYPHS.telegram.paths[0]?.d,
    );
  });
});

describe("connectorBrand", () => {
  it.each([
    ["google_drive", "gdrive"],
    ["gdrive", "gdrive"],
    ["drive", "gdrive"],
    ["aws", "s3"],
    ["s3", "s3"],
  ])("maps the connector type %s to %s", (connector, brand) => {
    expect(connectorBrand(connector)).toBe(brand);
  });

  it("has no mark for a connector type it does not know", () => {
    expect(connectorBrand("sharepoint")).toBeUndefined();
  });

  it("only ever names a brand the set draws", () => {
    // A spelling that maps to a name with no glyph would throw at render, in a
    // list, on whichever deployment happens to have that connector.
    for (const connector of ["google_drive", "gdrive", "drive", "github", "notion", "slack"]) {
      expect(isBrandName(connectorBrand(connector) ?? "")).toBe(true);
    }
  });
});

describe("isBrandName", () => {
  it("recognises a name the set draws", () => {
    expect(isBrandName("notion")).toBe(true);
  });

  it("rejects one it does not, rather than rendering a blank", () => {
    expect(isBrandName("sharepoint")).toBe(false);
  });
});
