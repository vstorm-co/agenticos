import { describe, expect, it } from "vitest";

import { partialArgs } from "./partial-args";
import {
  appName,
  framedElsewhere,
  applyEdits,
  clampHeight,
  imageNames,
  inlineImages,
  isVisualTool,
  resolveVisual,
  streamedDrawing,
  svgAspect,
  visualFilename,
  visualFrameUrl,
  visualKind,
} from "./visuals";

type Call = { id: string; name: string; args: Record<string, unknown> };

const draw = (id: string, args: Record<string, unknown>): Call => ({ id, name: "draw", args });
const revise = (id: string, args: Record<string, unknown>): Call => ({
  id,
  name: "revise_visual",
  args,
});

describe("the vocabulary", () => {
  it("knows which calls draw", () => {
    expect(isVisualTool("draw")).toBe(true);
    expect(isVisualTool("revise_visual")).toBe(true);
    expect(isVisualTool("read_visual")).toBe(false);
    expect(isVisualTool(undefined)).toBe(false);
  });

  it("keeps a height in range and falls back for nonsense", () => {
    expect(clampHeight(20)).toBe(160);
    expect(clampHeight(5000)).toBe(1200);
    expect(clampHeight(500.4)).toBe(500);
    expect(clampHeight("tall")).toBe(480);
    expect(clampHeight(Number.NaN, 300)).toBe(300);
  });

  it("knows the three kinds and nothing else", () => {
    expect(visualKind("svg")).toBe("svg");
    expect(visualKind("html")).toBe("html");
    expect(visualKind("mermaid")).toBe("mermaid");
    expect(visualKind("png")).toBeNull();
  });

  it("puts the frame on the content origin", () => {
    expect(visualFrameUrl("https://content.example.com/")).toBe(
      "https://content.example.com/api/v1/artifact-content/visual-frame",
    );
  });
});

describe("applyEdits", () => {
  it("applies each edit where it names exactly one place", () => {
    expect(
      applyEdits("a b c", [
        { old: "b", new: "B" },
        { old: "c", new: "" },
      ]),
    ).toBe("a B ");
  });

  it("refuses an edit that names no place or several", () => {
    expect(applyEdits("a", [{ old: "x", new: "y" }])).toBeNull();
    expect(applyEdits("a a", [{ old: "a", new: "b" }])).toBeNull();
  });
});

describe("resolveVisual", () => {
  const origin = draw("d", {
    title: "Flow",
    kind: "svg",
    height: 600,
    content: "<svg>one{{image:logo}}</svg>",
    images: [
      { name: "logo", source: "a.png" },
      { name: "unused", source: "u.png" },
      { source: "x" },
      "junk",
      null,
    ],
  });

  it("is a drawing as written", () => {
    expect(resolveVisual(origin, new Map())).toEqual({
      title: "Flow",
      kind: "svg",
      content: "<svg>one{{image:logo}}</svg>",
      height: 600,
      // Only what the drawing uses: `unused` is never fetched.
      images: { logo: "d" },
    });
  });

  it("applies revisions in order, with their titles and pictures", () => {
    const first = revise("r1", {
      visual_id: "d",
      edits: [{ old: "one", new: "two" }],
      title: "Renamed",
    });
    const second = revise("r2", {
      visual_id: "r1",
      edits: [{ old: "two", new: "three" }],
      title: "  ",
      images: [{ name: "logo", source: "b.png" }],
    });
    const known = new Map<string, Call>([
      ["d", origin],
      ["r1", first],
    ]);
    expect(resolveVisual(second, known)).toEqual({
      title: "Renamed",
      kind: "svg",
      content: "<svg>three{{image:logo}}</svg>",
      height: 600,
      images: { logo: "r2" },
    });
  });

  it("keeps no more pictures than a drawing may use", () => {
    const names = ["a", "b", "c", "d", "e", "f", "g"];
    const crowded = draw("c", {
      title: "Many",
      kind: "html",
      content: names.map((name) => `{{image:${name}}}`).join(""),
      images: names.map((name) => ({ name, source: `${name}.png` })),
    });
    expect(Object.keys(resolveVisual(crowded, new Map())?.images ?? {})).toHaveLength(6);
  });

  it("cannot rebuild what is not loaded, malformed or no longer applies", () => {
    expect(resolveVisual(revise("r", { visual_id: "gone", edits: [] }), new Map())).toBeNull();
    expect(resolveVisual(revise("r", { visual_id: 3, edits: [] }), new Map())).toBeNull();
    expect(resolveVisual(draw("d", { kind: "pdf", content: "x" }), new Map())).toBeNull();
    expect(resolveVisual(draw("d", { kind: "svg" }), new Map())).toBeNull();
    const known = new Map<string, Call>([["d", origin]]);
    for (const edits of [
      "nope",
      [null],
      [{ old: "", new: "x" }],
      [{ old: "a", new: 3 }],
      [{ old: "missing", new: "x" }],
    ]) {
      expect(resolveVisual(revise("r", { visual_id: "d", edits }), known)).toBeNull();
    }
  });

  it("gives up on a chain that never ends", () => {
    const loop = revise("x", { visual_id: "x", edits: [] });
    expect(resolveVisual(loop, new Map([["x", loop]]))).toBeNull();
  });

  it("takes an untitled drawing as untitled", () => {
    expect(resolveVisual(draw("d", { kind: "html", content: "<p/>" }), new Map())?.title).toBe("");
  });
});

describe("streamedDrawing", () => {
  it("shows what has arrived, and the kind and height only once complete", () => {
    expect(streamedDrawing(partialArgs('{"title": "Fl'))).toEqual({
      title: "Fl",
      kind: null,
      height: null,
      content: "",
    });
    expect(
      streamedDrawing(
        partialArgs('{"title": "Flow", "kind": "svg", "height": 9000, "content": "<s'),
      ),
    ).toEqual({ title: "Flow", kind: "svg", height: 1200, content: "<s" });
  });

  it("ignores fields of the wrong type", () => {
    expect(streamedDrawing({ title: { value: 3, complete: true } })).toEqual({
      title: "",
      kind: null,
      height: null,
      content: "",
    });
  });
});

describe("pictures", () => {
  it("names a call's pictures and ignores what is not one", () => {
    expect(imageNames({ images: [{ name: "a" }, { name: 2 }, null, "b"] })).toEqual(["a"]);
    expect(imageNames({ images: "a" })).toEqual([]);
  });

  it("inlines a known picture and leaves an unknown one", () => {
    expect(inlineImages('<img src="{{image:a}}"><img src="{{image:b}}">', { a: "data:x" })).toBe(
      '<img src="data:x"><img src="{{image:b}}">',
    );
  });
});

describe("svgAspect", () => {
  it("reads the viewBox", () => {
    expect(svgAspect('<svg viewBox="0 0 840 1188">')).toBeCloseTo(1188 / 840);
    expect(svgAspect("<svg viewBox='0,0,100,50'>")).toBe(0.5);
  });

  it("has no aspect without a usable viewBox", () => {
    expect(svgAspect("<svg width='10'>")).toBeNull();
    expect(svgAspect('<svg viewBox="0 0 0 10">')).toBeNull();
  });
});

describe("names for files and apps", () => {
  it("turns a title into an app name", () => {
    expect(appName("Plakat A3 — Łódź & Żółć!")).toBe("plakat-a3-lodz-zolc");
    expect(appName("!!!")).toBe("visual");
    expect(appName("a".repeat(70))).toHaveLength(64);
  });

  it("gives each kind its extension", () => {
    expect(visualFilename("Flow", "svg")).toBe("flow.svg");
    expect(visualFilename("Flow", "html")).toBe("flow.html");
    expect(visualFilename("Flow", "mermaid")).toBe("flow.mmd");
  });
});

describe("framedElsewhere", () => {
  it("is false for a console that is the whole window", () => {
    expect(framedElsewhere()).toBe(false);
  });
});
