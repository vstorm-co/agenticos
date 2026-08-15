import { describe, expect, it } from "vitest";

import type { SectionDef } from "./layouts";
import {
  applySectionsFilter,
  filterableSectionIds,
  formatSectionsParam,
  isFilterable,
  parseSectionsParam,
  sectionLabel,
} from "./sections";

const SECTIONS: SectionDef[] = [
  { id: "attention", titleKey: "attention", entries: [] },
  { id: "usage", titleKey: "usage", entries: [] },
  { id: "workspace", titleKey: null, entries: [] },
];

/** What a saved arrangement looks like: bands named by the person, not by a key. */
const OWN_SECTIONS: SectionDef[] = [
  { id: "custom-0", titleKey: null, entries: [] },
  { id: "custom-1", titleKey: null, title: "Money", entries: [] },
  { id: "custom-2", titleKey: null, title: "  ", entries: [] },
];

describe("filterableSectionIds", () => {
  it("offers only titled sections - hiding the untitled one would empty the page", () => {
    expect(filterableSectionIds(SECTIONS)).toEqual(["attention", "usage"]);
  });

  it("offers a band a person named themselves, which is a name like any other", () => {
    // Reading `titleKey` alone took the whole control away the moment somebody
    // saved an arrangement, even one that kept every heading it started with.
    expect(filterableSectionIds(OWN_SECTIONS)).toEqual(["custom-1"]);
  });

  it("a divider with a blank caption is a rule, not a name", () => {
    expect(isFilterable({ id: "x", titleKey: null, title: "   ", entries: [] })).toBe(false);
  });
});

describe("sectionLabel", () => {
  const t = (key: string) => `translated:${key}`;

  it("prefers the caption a person typed over the curated key", () => {
    expect(sectionLabel({ id: "a", titleKey: "usage", title: "Money", entries: [] }, t)).toBe(
      "Money",
    );
    expect(sectionLabel({ id: "b", titleKey: "usage", entries: [] }, t)).toBe(
      "translated:sections.usage",
    );
    expect(sectionLabel({ id: "c", titleKey: null, entries: [] }, t)).toBe("");
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

  it("hides an unselected band a person named, and keeps their unnamed one", () => {
    const filtered = applySectionsFilter(OWN_SECTIONS, ["custom-0"]);

    expect(filtered.map((section) => section.id)).toEqual(["custom-0", "custom-2"]);
  });
});

describe("formatSectionsParam", () => {
  it("round-trips a selection and clears an empty one", () => {
    expect(formatSectionsParam(["attention", "usage"])).toBe("attention,usage");
    expect(formatSectionsParam(null)).toBeNull();
    expect(formatSectionsParam([])).toBeNull();
  });
});
