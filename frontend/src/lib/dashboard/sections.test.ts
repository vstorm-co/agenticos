import { describe, expect, it } from "vitest";

import type { SectionDef } from "./layouts";
import {
  applySectionsFilter,
  filterableSectionIds,
  formatSectionsParam,
  parseSectionsParam,
} from "./sections";

const SECTIONS: SectionDef[] = [
  { id: "attention", titleKey: "attention", entries: [] },
  { id: "usage", titleKey: "usage", entries: [] },
  { id: "workspace", titleKey: null, entries: [] },
];

describe("filterableSectionIds", () => {
  it("offers only titled sections - hiding the untitled one would empty the page", () => {
    expect(filterableSectionIds(SECTIONS)).toEqual(["attention", "usage"]);
  });
});

describe("parseSectionsParam", () => {
  it("keeps a valid selection", () => {
    expect(parseSectionsParam("usage", SECTIONS)).toEqual(["usage"]);
  });

  it("drops ids the caller's layout does not have - the filter never reveals", () => {
    // "deployment" might be a real section on somebody else's dashboard; a
    // pasted link must not conjure it here.
    expect(parseSectionsParam("usage,deployment", SECTIONS)).toEqual(["usage"]);
  });

  it("a selection of everything is no filter at all", () => {
    expect(parseSectionsParam("attention,usage", SECTIONS)).toBeNull();
  });

  it("an empty or fully-invalid selection means no filter, never zero sections", () => {
    expect(parseSectionsParam(null, SECTIONS)).toBeNull();
    expect(parseSectionsParam("", SECTIONS)).toBeNull();
    expect(parseSectionsParam("deployment,ghost", SECTIONS)).toBeNull();
  });

  it("survives stray spaces and commas", () => {
    expect(parseSectionsParam(" usage , ,", SECTIONS)).toEqual(["usage"]);
  });
});

describe("applySectionsFilter", () => {
  it("hides the unselected titled sections and keeps the untitled ones", () => {
    const filtered = applySectionsFilter(SECTIONS, ["usage"]);

    expect(filtered.map((section) => section.id)).toEqual(["usage", "workspace"]);
  });

  it("null passes everything through", () => {
    expect(applySectionsFilter(SECTIONS, null)).toBe(SECTIONS);
  });
});

describe("formatSectionsParam", () => {
  it("round-trips a selection and clears an empty one", () => {
    expect(formatSectionsParam(["attention", "usage"])).toBe("attention,usage");
    expect(formatSectionsParam(null)).toBeNull();
    expect(formatSectionsParam([])).toBeNull();
  });
});
