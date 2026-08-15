import { describe, expect, it } from "vitest";

import { isWidget, LAYOUTS, type LayoutItem } from "./layouts";
import { WIDGETS } from "./registry";
import {
  CUSTOM_SECTION_ID,
  flattenDefaultToItems,
  groupItems,
  newDivider,
  newPlacement,
  resolveEffectiveLayout,
  sanitizeEntries,
  sectionsFromItems,
  toStored,
  type StoredEntry,
  ungroupItems,
  visibleItems,
  widgetCatalog,
} from "./preference";
import { Perm, type Permission } from "@/types/permissions";

const holds =
  (...held: Permission[]) =>
  (permission: Permission) =>
    held.includes(permission);

describe("sanitizeEntries", () => {
  it("keeps known widgets and preserves order and duplicates, filling heights", () => {
    const stored: StoredEntry[] = [
      { widget: "runs", span: "s8", rows: "r4" },
      { widget: "runs", span: "s6" },
    ];
    // The first keeps its stored height; the second, saved before heights,
    // grows the widget's default.
    expect(sanitizeEntries(stored)).toEqual([
      { widget: "runs", span: "s8", rows: "r4" },
      { widget: "runs", span: "s6", rows: WIDGETS.runs.defaultRows },
    ]);
  });

  it("drops a widget id the registry no longer knows", () => {
    const stored: StoredEntry[] = [
      { widget: "retired-widget", span: "s6" },
      { widget: "spend", span: "s6" },
    ];
    expect(sanitizeEntries(stored)).toEqual([
      { widget: "spend", span: "s6", rows: WIDGETS.spend.defaultRows },
    ]);
  });

  it("replaces a span or height outside the closed set with the widget's default", () => {
    expect(sanitizeEntries([{ widget: "runs", span: "s99", rows: "r9" }])).toEqual([
      { widget: "runs", span: WIDGETS.runs.defaultSpan, rows: WIDGETS.runs.defaultRows },
    ]);
  });

  it("reads a divider, keeping a preset accent and carrying collapse", () => {
    expect(
      sanitizeEntries([{ kind: "section", label: "Mine", accent: "violet", collapsed: true }]),
    ).toEqual([{ kind: "section", label: "Mine", accent: "violet", collapsed: true }]);
  });

  it("lower-cases a custom hex accent and drops an accent the palette no longer knows", () => {
    expect(sanitizeEntries([{ kind: "section", label: "A", accent: "#ABCDEF" }])).toEqual([
      { kind: "section", label: "A", accent: "#abcdef" },
    ]);
    expect(sanitizeEntries([{ kind: "section", label: "B", accent: "chartreuse" }])).toEqual([
      { kind: "section", label: "B", accent: "neutral" },
    ]);
  });
});

describe("flattenDefaultToItems", () => {
  it("turns each titled section into a divider then its cards, every card sized", () => {
    const items = flattenDefaultToItems(LAYOUTS.steward, (section) => section.titleKey ?? "");
    const dividers = items.filter((item) => item.kind === "section");
    // Titled sections only: the summary band carries no heading, and an
    // untitled section deliberately contributes no divider.
    const titled = LAYOUTS.steward.filter((section) => section.titleKey !== null);
    expect(dividers).toHaveLength(titled.length);
    expect(items[0]).toEqual({ kind: "section", label: "deployment", accent: "neutral" });
    // The summary follows the deployment band's cards, headingless.
    expect(items.find((item) => "widget" in item && item.widget === "summary")).toEqual({
      widget: "summary",
      span: "s12",
      rows: "r3",
    });
    const widgets = items.filter((item) => item.kind !== "section");
    expect(widgets.every((item) => "rows" in item && item.rows !== undefined)).toBe(true);
  });

  it("gives an untitled section no divider — its cards lead, headingless", () => {
    const items = flattenDefaultToItems(LAYOUTS.member, () => "");
    expect(items.some((item) => item.kind === "section")).toBe(false);
    expect(items).toHaveLength(LAYOUTS.member.flatMap((section) => section.entries).length);
  });
});

describe("groupItems / ungroupItems", () => {
  it("groups at dividers and round-trips back to the flat list", () => {
    const items: LayoutItem[] = [
      { widget: "runs", span: "s8", rows: "r4" },
      { kind: "section", label: "Mine", accent: "violet" },
      { widget: "spend", span: "s6", rows: "r3" },
    ];
    const sections = groupItems(items);
    expect(sections).toEqual([
      { divider: null, widgets: [{ widget: "runs", span: "s8", rows: "r4" }] },
      {
        divider: { kind: "section", label: "Mine", accent: "violet" },
        widgets: [{ widget: "spend", span: "s6", rows: "r3" }],
      },
    ]);
    expect(ungroupItems(sections)).toEqual(items);
  });

  it("keeps no leading section when the first item is a divider", () => {
    const sections = groupItems([
      { kind: "section", label: "A", accent: "neutral" },
      { widget: "runs", span: "s8", rows: "r3" },
    ]);
    expect(sections).toHaveLength(1);
    expect(sections[0]!.divider?.label).toBe("A");
  });
});

describe("sectionsFromItems", () => {
  it("opens a section at a divider, carrying its accent and collapse", () => {
    const sections = sectionsFromItems([
      { kind: "section", label: "Mine", accent: "violet", collapsed: true },
      { widget: "spend", span: "s6", rows: "r3" },
    ]);
    expect(sections).toEqual([
      {
        id: `${CUSTOM_SECTION_ID}-1`,
        titleKey: null,
        title: "Mine",
        accent: "violet",
        collapsed: true,
        entries: [{ widget: "spend", span: "s6", rows: "r3" }],
      },
    ]);
  });

  it("drops a divider with no cards under it", () => {
    expect(sectionsFromItems([{ kind: "section", label: "Empty", accent: "neutral" }])).toEqual([]);
  });
});

describe("resolveEffectiveLayout", () => {
  it("falls back to the audience default when nothing is stored", () => {
    expect(resolveEffectiveLayout("steward", null)).toBe(LAYOUTS.steward);
  });

  it("wraps a stored arrangement as one untitled custom section", () => {
    expect(resolveEffectiveLayout("member", [{ widget: "runs", span: "s8", rows: "r4" }])).toEqual([
      {
        id: CUSTOM_SECTION_ID,
        titleKey: null,
        entries: [{ widget: "runs", span: "s8", rows: "r4" }],
      },
    ]);
  });

  it("drops a section left empty once its unknown widgets are sanitized out", () => {
    expect(resolveEffectiveLayout("member", [{ widget: "retired", span: "s8" }])).toEqual([]);
  });
});

describe("visibleItems", () => {
  it("drops a widget the caller may not see but keeps every divider", () => {
    const items: LayoutItem[] = [
      { kind: "section", label: "Mine", accent: "neutral" },
      { widget: "runs", span: "s8", rows: "r3" },
      { widget: "platform", span: "s8", rows: "r3" },
    ];
    const visible = visibleItems(items, holds(Perm.runsView), false);
    expect(visible).toEqual([
      { kind: "section", label: "Mine", accent: "neutral" },
      { widget: "runs", span: "s8", rows: "r3" },
    ]);
  });
});

describe("widgetCatalog", () => {
  it("offers only widgets whose gate the caller passes", () => {
    const catalog = widgetCatalog(holds(Perm.runsView), false).map((def) => def.id);
    expect(catalog).toContain("runs");
    expect(catalog).not.toContain("platform");
    expect(catalog).not.toContain("approvals");
  });

  it("gives an app admin the deployment widgets", () => {
    expect(widgetCatalog(() => false, true).map((def) => def.id)).toContain("platform");
  });
});

describe("newPlacement / newDivider", () => {
  it("mints a card at the widget's default size and a bare neutral divider", () => {
    expect(newPlacement("runs")).toEqual({
      widget: "runs",
      span: WIDGETS.runs.defaultSpan,
      rows: WIDGETS.runs.defaultRows,
    });
    expect(newDivider()).toEqual({ kind: "section", label: "", accent: "neutral" });
  });
});

describe("toStored", () => {
  it("strips a placement to what is persisted, height included", () => {
    expect(
      toStored([{ widget: "runs", span: "s8", rows: "r4", titleKey: "widgets.x.title" }]),
    ).toEqual([{ widget: "runs", span: "s8", rows: "r4" }]);
  });

  it("fills a missing height so the wire always carries one", () => {
    expect(toStored([{ widget: "spend", span: "s6" }])).toEqual([
      { widget: "spend", span: "s6", rows: WIDGETS.spend.defaultRows },
    ]);
  });

  it("persists a divider's label and accent, and its collapse only when set", () => {
    expect(toStored([{ kind: "section", label: "Mine", accent: "#abcdef" }])).toEqual([
      { kind: "section", label: "Mine", accent: "#abcdef" },
    ]);
    expect(
      toStored([{ kind: "section", label: "Mine", accent: "violet", collapsed: true }]),
    ).toEqual([{ kind: "section", label: "Mine", accent: "violet", collapsed: true }]);
  });
});

describe("a card's own settings, read back", () => {
  it("keeps a window, a style and a narrowing the widget still offers", () => {
    const [entry] = sanitizeEntries([
      {
        widget: "runs",
        span: "s8",
        rows: "r3",
        options: { period: "90d", style: "bars", agent_id: "agent-1", user_id: "user-1" },
      },
    ]);

    expect(isWidget(entry!) && entry.options).toEqual({
      period: "90d",
      style: "bars",
      agentId: "agent-1",
      userId: "user-1",
    });
  });

  it("drops a knob the widget does not offer, rather than sending it back", () => {
    // The members card has no window and no subject. A stored agent filter on
    // it would otherwise be written back on the next save and narrow a request
    // nobody asked to narrow.
    const [entry] = sanitizeEntries([
      { widget: "members", span: "s6", options: { period: "90d", agent_id: "agent-1" } },
    ]);

    expect(isWidget(entry!) && entry.options).toBeUndefined();
  });

  it("drops a window this build no longer has", () => {
    const [entry] = sanitizeEntries([
      { widget: "runs", span: "s8", options: { period: "5y", style: "bars" } },
    ]);

    expect(isWidget(entry!) && entry.options).toEqual({ style: "bars" });
  });

  it("carries no options key at all for a card that follows the page", () => {
    // "Follows the page" is the absence of settings, not an empty object - the
    // difference between tracking the filter and happening to agree with it.
    const [entry] = sanitizeEntries([{ widget: "runs", span: "s8", options: {} }]);

    expect(isWidget(entry!) && "options" in entry).toBe(false);
  });

  it("writes them back snake_cased, the way the API takes them", () => {
    const stored = toStored([
      { widget: "runs", span: "s8", rows: "r3", options: { period: "90d", agentId: "agent-1" } },
    ]);

    expect(stored[0]?.options).toEqual({
      period: "90d",
      style: undefined,
      agent_id: "agent-1",
      user_id: undefined,
    });
  });
});
