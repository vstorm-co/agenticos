import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Glyph } from "@/lib/brand-glyphs.generated";

import { GlyphIcon } from "./glyph";

const ONE_PATH: Glyph = { viewBox: "0 0 24 24", paths: [{ d: "M0 0h24v24H0z" }] };

describe("GlyphIcon", () => {
  it("draws every path of a mark, in order", () => {
    // A mark that silently loses a layer still renders and still looks like a
    // logo - Azure is three overlapping sheets, and any two of them is a
    // different shape.
    const layered: Glyph = {
      viewBox: "0 0 24 24",
      fillRule: "evenodd",
      paths: [{ d: "M1 1h1v1H1z", fillOpacity: 0.5 }, { d: "M2 2h1v1H2z" }],
    };
    const { container } = render(<GlyphIcon glyph={layered} />);
    const paths = container.querySelectorAll("path");

    expect([...paths].map((path) => path.getAttribute("d"))).toEqual([
      "M1 1h1v1H1z",
      "M2 2h1v1H2z",
    ]);
    expect(paths[0]).toHaveAttribute("fill-opacity", "0.5");
    expect(paths[1]).not.toHaveAttribute("fill-opacity");
  });

  it("draws a mark of several colours path by path, unless the caller asks for the text colour", () => {
    // Google's G on a sign-in button is four shapes in four colours; one fill
    // for the whole mark is a different, flat logo.
    const fourColour: Glyph = {
      viewBox: "0 0 24 24",
      paths: [
        { d: "M1 1h1v1H1z", fill: "#4285F4" },
        { d: "M2 2h1v1H2z", fill: "#34A853" },
      ],
    };

    const coloured = render(<GlyphIcon glyph={fourColour} />).container.querySelectorAll("path");
    expect([...coloured].map((path) => path.getAttribute("fill"))).toEqual(["#4285F4", "#34A853"]);

    const mono = render(<GlyphIcon glyph={fourColour} mono />).container;
    expect(mono.firstElementChild).toHaveAttribute("fill", "currentColor");
    expect(mono.querySelectorAll("path[fill]")).toHaveLength(0);
  });

  it("carries the fill rule a mark's holes depend on", () => {
    const { container } = render(<GlyphIcon glyph={{ ...ONE_PATH, fillRule: "evenodd" }} />);
    expect(container.firstElementChild).toHaveAttribute("fill-rule", "evenodd");
  });

  it("leaves the fill rule off a mark that does not need one", () => {
    // SVG's default is `nonzero`; writing it out would be a second way of
    // saying the same thing on two thirds of the set.
    const { container } = render(<GlyphIcon glyph={ONE_PATH} />);
    expect(container.firstElementChild).not.toHaveAttribute("fill-rule");
  });

  it("draws in currentColor at the caller's size", () => {
    const { container } = render(<GlyphIcon glyph={ONE_PATH} className="h-5 w-5" />);
    const svg = container.firstElementChild;

    expect(svg).toHaveAttribute("fill", "currentColor");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
    expect(svg).toHaveClass("h-5", "w-5");
  });

  it("draws a coloured brand in its colour, unless the caller asks for the text colour", () => {
    const coloured = { ...ONE_PATH, color: "#D97757" };

    expect(render(<GlyphIcon glyph={coloured} />).container.firstElementChild).toHaveAttribute(
      "fill",
      "#D97757",
    );
    expect(render(<GlyphIcon glyph={coloured} mono />).container.firstElementChild).toHaveAttribute(
      "fill",
      "currentColor",
    );
  });
});
