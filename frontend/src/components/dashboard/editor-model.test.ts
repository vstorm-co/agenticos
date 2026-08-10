import { describe, expect, it } from "vitest";

import type { DividerEntry, LayoutItem } from "@/lib/dashboard/layouts";
import {
  addWidgetToSection,
  type EditorSection,
  type EditorWidget,
  fromEditorSections,
  locate,
  moveSection,
  moveWidget,
  patchDivider,
  removeSection,
  removeWidget,
  resizeWidget,
  swapWidgets,
  toEditorSections,
} from "./editor-model";

const card = (uid: string, widget: string): EditorWidget =>
  ({ uid, widget, span: "s6" }) as EditorWidget;

const divider = (label: string): DividerEntry => ({ kind: "section", label, accent: "neutral" });

const section = (
  uid: string,
  div: DividerEntry | null,
  widgets: EditorWidget[],
): EditorSection => ({
  uid,
  divider: div,
  widgets,
});

/** The card ids in each section, in order — the shape every assertion reads. */
const shape = (sections: EditorSection[]): Array<{ divider: string | null; widgets: string[] }> =>
  sections.map((s) => ({
    divider: s.divider ? s.divider.label : null,
    widgets: s.widgets.map((w) => w.widget),
  }));

describe("toEditorSections / fromEditorSections", () => {
  it("groups a flat list into sections and inverts back to it", () => {
    const items: LayoutItem[] = [
      { widget: "runs", span: "s8" },
      { kind: "section", label: "Usage", accent: "blue" },
      { widget: "spend", span: "s6" },
      { widget: "agents", span: "s6" },
    ];
    let n = 0;
    const sections = toEditorSections(items, () => `u${n++}`);

    expect(shape(sections)).toEqual([
      { divider: null, widgets: ["runs"] },
      { divider: "Usage", widgets: ["spend", "agents"] },
    ]);
    // Every minted uid is distinct, and the round trip drops them again.
    const uids = [
      ...sections.map((s) => s.uid),
      ...sections.flatMap((s) => s.widgets.map((w) => w.uid)),
    ];
    expect(new Set(uids).size).toBe(uids.length);
    expect(fromEditorSections(sections)).toEqual(items);
  });
});

describe("locate", () => {
  const sections = [
    section("s0", null, [card("a", "runs")]),
    section("s1", divider("U"), [card("b", "spend")]),
  ];

  it("finds a card's section and index", () => {
    expect(locate(sections, "b")).toEqual({ sectionUid: "s1", index: 0 });
  });

  it("answers null for a card that is not there", () => {
    expect(locate(sections, "missing")).toBeNull();
  });
});

describe("moveWidget", () => {
  it("reorders within a section", () => {
    const before = [
      section("s0", null, [card("a", "runs"), card("b", "spend"), card("c", "agents")]),
    ];
    const after = moveWidget(before, "c", "s0", 0);
    expect(shape(after)).toEqual([{ divider: null, widgets: ["agents", "runs", "spend"] }]);
  });

  it("moves a card into another section at the index given", () => {
    const before = [
      section("s0", null, [card("a", "runs")]),
      section("s1", divider("U"), [card("b", "spend"), card("c", "agents")]),
    ];
    const after = moveWidget(before, "a", "s1", 1);
    expect(shape(after)).toEqual([
      { divider: null, widgets: [] },
      { divider: "U", widgets: ["spend", "runs", "agents"] },
    ]);
  });

  it("clamps an index past the end", () => {
    const before = [section("s0", null, [card("a", "runs"), card("b", "spend")])];
    const after = moveWidget(before, "a", "s0", 99);
    expect(shape(after)).toEqual([{ divider: null, widgets: ["spend", "runs"] }]);
  });

  it("returns the input untouched when the card is unknown", () => {
    const before = [section("s0", null, [card("a", "runs")])];
    expect(moveWidget(before, "missing", "s0", 0)).toBe(before);
  });
});

describe("swapWidgets", () => {
  it("is a no-op when the two ids are the same", () => {
    const before = [section("s0", null, [card("a", "runs")])];
    expect(swapWidgets(before, "a", "a")).toBe(before);
  });

  it("is a no-op when either card is missing", () => {
    const before = [section("s0", null, [card("a", "runs")])];
    expect(swapWidgets(before, "a", "missing")).toBe(before);
  });

  it("exchanges two cards within one section", () => {
    const before = [
      section("s0", null, [card("a", "runs"), card("b", "spend"), card("c", "agents")]),
    ];
    const after = swapWidgets(before, "a", "c");
    expect(shape(after)).toEqual([{ divider: null, widgets: ["agents", "spend", "runs"] }]);
  });

  it("exchanges two cards across sections, each taking the other's slot", () => {
    const before = [
      section("s0", null, [card("a", "runs"), card("b", "spend")]),
      section("s1", divider("U"), [card("c", "agents"), card("d", "health")]),
    ];
    const after = swapWidgets(before, "a", "d");
    expect(shape(after)).toEqual([
      { divider: null, widgets: ["health", "spend"] },
      { divider: "U", widgets: ["agents", "runs"] },
    ]);
  });
});

describe("moveSection", () => {
  const build = () => [
    section("lead", null, [card("a", "runs")]),
    section("s1", divider("One"), [card("b", "spend")]),
    section("s2", divider("Two"), [card("c", "agents")]),
  ];

  it("reorders dividered sections while pinning the headingless lead to the front", () => {
    const after = moveSection(build(), "s2", 0);
    expect(shape(after)).toEqual([
      { divider: null, widgets: ["runs"] },
      { divider: "Two", widgets: ["agents"] },
      { divider: "One", widgets: ["spend"] },
    ]);
  });

  it("refuses to move the headingless leading section", () => {
    const before = build();
    expect(moveSection(before, "lead", 2)).toBe(before);
  });
});

describe("resizeWidget", () => {
  it("sets width and height on the target card only", () => {
    const before = [section("s0", null, [card("a", "runs"), card("b", "spend")])];
    const after = resizeWidget(before, "a", "s12", "r4");
    expect(after[0]!.widgets[0]).toMatchObject({ widget: "runs", span: "s12", rows: "r4" });
    expect(after[0]!.widgets[1]).toMatchObject({ widget: "spend", span: "s6" });
  });
});

describe("removeWidget / addWidgetToSection", () => {
  it("drops a card", () => {
    const before = [section("s0", null, [card("a", "runs"), card("b", "spend")])];
    expect(shape(removeWidget(before, "a"))).toEqual([{ divider: null, widgets: ["spend"] }]);
  });

  it("appends a card to the end of a section", () => {
    const before = [section("s0", divider("U"), [card("a", "runs")])];
    const after = addWidgetToSection(before, "s0", card("b", "spend"));
    expect(shape(after)).toEqual([{ divider: "U", widgets: ["runs", "spend"] }]);
  });
});

describe("removeSection", () => {
  it("merges the section's cards into the previous one", () => {
    const before = [
      section("s0", divider("One"), [card("a", "runs")]),
      section("s1", divider("Two"), [card("b", "spend"), card("c", "agents")]),
    ];
    expect(shape(removeSection(before, "s1"))).toEqual([
      { divider: "One", widgets: ["runs", "spend", "agents"] },
    ]);
  });

  it("turns the cards into a headingless leading section when there is no previous", () => {
    const before = [section("s0", divider("One"), [card("a", "runs")])];
    expect(shape(removeSection(before, "s0"))).toEqual([{ divider: null, widgets: ["runs"] }]);
  });

  it("drops a heading that has no cards without leaving an empty band", () => {
    const before = [
      section("s0", divider("One"), [card("a", "runs")]),
      section("s1", divider("Empty"), []),
    ];
    expect(shape(removeSection(before, "s1"))).toEqual([{ divider: "One", widgets: ["runs"] }]);
  });
});

describe("patchDivider", () => {
  it("changes a section's heading in place", () => {
    const before = [section("s0", divider("Old"), [card("a", "runs")])];
    const after = patchDivider(before, "s0", { label: "New", accent: "rose", collapsed: true });
    expect(after[0]!.divider).toEqual({
      kind: "section",
      label: "New",
      accent: "rose",
      collapsed: true,
    });
  });

  it("leaves a headingless leading section untouched", () => {
    const before = [section("lead", null, [card("a", "runs")])];
    expect(patchDivider(before, "lead", { label: "X" })).toEqual(before);
  });
});
