/**
 * The personalization layer: a person's own arrangement over the audience
 * default the layout resolves.
 *
 *   effective layout = stored preference ?? audience default
 *   visible          = visibleSections(effective, can, isAppAdmin)   // gate last
 *
 * Everything here is the *effective* half - turning a stored preference into a
 * section list, and the transforms that build one. The gate is not here: it is
 * `visibleSections` in `layouts.ts`, run last on whatever this produces, which
 * is what stops a preference ever revealing a widget the caller may not see. A
 * preference can only reorder or hide.
 *
 * An arrangement is a flat list of items, each a widget placement or a section
 * divider. Two groupings sit over that flat list, and both live here so they
 * cannot drift: `sectionsFromItems` is the page's read (grouped into `SectionDef`
 * for rendering), and `groupItems`/`ungroupItems` is the editor's, which keeps
 * the divider object itself so its label, accent and collapse are editable. A
 * section is the divider plus the cards up to the next divider; cards before
 * the first divider are a headingless leading section.
 *
 * Nothing about a stored preference is trusted on read. A widget id retired
 * since it was saved is dropped rather than rendered as a blank card, a span
 * the grid no longer knows is replaced with the widget's default, and an accent
 * the palette no longer knows falls back to neutral - all in `sanitizeEntries`,
 * before the layout is ever built.
 */

import {
  isDivider,
  LAYOUTS,
  ROW_CLASS,
  SPAN_CLASS,
  type AudienceId,
  type DividerEntry,
  type LayoutEntry,
  type LayoutItem,
  type SectionDef,
} from "./layouts";
import {
  normaliseAccent,
  WIDGETS,
  WIDGET_IDS,
  type Rows,
  type Span,
  type WidgetDef,
  type WidgetId,
} from "./registry";
import type { Permission } from "@/types/permissions";

/** A placement as it comes back from the API - permissive, possibly stale. */
export interface StoredEntry {
  /** `"section"` for a divider; absent or `"widget"` for a widget placement. */
  kind?: "widget" | "section";
  widget?: string;
  span?: string;
  /** Card height in grid rows; absent on arrangements saved before heights. */
  rows?: string | null;
  /** A divider's caption. */
  label?: string;
  /** A divider's colour - a preset name, a `#rrggbb` hex, or neutral. */
  accent?: string;
  /** Whether a divider's section is folded to its heading. */
  collapsed?: boolean;
}

/** The id of the leading (pre-first-divider) section a saved arrangement renders as. */
export const CUSTOM_SECTION_ID = "custom";

const VALID_SPANS = new Set<string>(Object.keys(SPAN_CLASS));
const VALID_ROWS = new Set<string>(Object.keys(ROW_CLASS));

/**
 * Turn stored entries into layout items the editor and page can use, dropping
 * what no longer makes sense and filling in what a person's grid needs:
 *
 * - an entry tagged `"section"` becomes a divider, its label trimmed to length,
 *   its accent normalised (an unknown one falls back to neutral) and its
 *   collapse carried through;
 * - an unknown (renamed or retired) widget id is left out entirely;
 * - a span outside the grid's closed set falls back to the widget's default,
 *   rather than rendering at a width the grid cannot express;
 * - a missing or out-of-set height falls back to the widget's default height,
 *   so an arrangement saved before heights existed grows an explicit one and
 *   every arranged card has a height to resize from.
 */
export function sanitizeEntries(stored: StoredEntry[]): LayoutItem[] {
  const items: LayoutItem[] = [];
  for (const entry of stored) {
    if (entry.kind === "section") {
      const divider: DividerEntry = {
        kind: "section",
        label: (entry.label ?? "").slice(0, 60),
        accent: normaliseAccent(entry.accent),
      };
      if (entry.collapsed) divider.collapsed = true;
      items.push(divider);
      continue;
    }
    const def = WIDGETS[entry.widget as WidgetId];
    if (!def) continue;
    const span = (entry.span && VALID_SPANS.has(entry.span) ? entry.span : def.defaultSpan) as Span;
    const rows = (entry.rows && VALID_ROWS.has(entry.rows) ? entry.rows : def.defaultRows) as Rows;
    items.push({ widget: def.id, span, rows });
  }
  return items;
}

/**
 * Turn an audience default into the editor's starting item list, so its curated
 * sections arrive as real, editable dividers rather than fixed headings a
 * person cannot rename or recolour. A titled section becomes a divider carrying
 * its resolved heading and accent, followed by its widgets; an untitled one
 * (the member's whole page) contributes its widgets bare, as a headingless
 * leading section. The title is resolved by the caller, which holds the
 * translator; a per-entry title override is not preserved, the same as it was
 * never persisted.
 */
export function flattenDefaultToItems(
  sections: SectionDef[],
  resolveTitle: (section: SectionDef) => string,
): LayoutItem[] {
  const items: LayoutItem[] = [];
  for (const section of sections) {
    const title = resolveTitle(section).trim();
    if (title) {
      items.push({ kind: "section", label: title, accent: section.accent ?? "neutral" });
    }
    for (const entry of section.entries) {
      items.push({
        widget: entry.widget,
        span: entry.span,
        rows: entry.rows ?? WIDGETS[entry.widget].defaultRows,
      });
    }
  }
  return items;
}

/**
 * Group a flat arrangement into sections at its dividers, for the page: cards
 * before the first divider form an untitled leading section, and each divider
 * opens a new one carrying its label, accent and collapse. A section that ends
 * up empty — a divider with no cards under it, or one whose cards were all gated
 * out — is dropped heading and all, the rule `visibleSections` applies to the
 * defaults.
 */
export function sectionsFromItems(items: LayoutItem[]): SectionDef[] {
  const sections: SectionDef[] = [];
  let current: SectionDef = { id: CUSTOM_SECTION_ID, titleKey: null, entries: [] };
  let dividerCount = 0;
  const flush = () => {
    if (current.entries.length > 0) sections.push(current);
  };
  for (const item of items) {
    if (isDivider(item)) {
      flush();
      dividerCount += 1;
      current = {
        id: `${CUSTOM_SECTION_ID}-${dividerCount}`,
        titleKey: null,
        title: item.label,
        accent: item.accent,
        collapsed: item.collapsed,
        entries: [],
      };
    } else {
      current.entries.push(item);
    }
  }
  flush();
  return sections;
}

/** A section as the editor works on it: the divider itself (or none for the
 * leading group) and the cards beneath it, so both are directly editable. */
export interface ItemSection {
  divider: DividerEntry | null;
  widgets: LayoutEntry[];
}

/**
 * Group a flat item list into editor sections, keeping the divider object so
 * its label, accent and collapse can be edited in place. The leading section
 * (cards before the first divider) is kept only when it holds cards, so it
 * never shows as an empty headingless band.
 */
export function groupItems(items: LayoutItem[]): ItemSection[] {
  const leading: ItemSection = { divider: null, widgets: [] };
  const sections: ItemSection[] = [];
  let current: ItemSection | null = null;
  for (const item of items) {
    if (isDivider(item)) {
      current = { divider: item, widgets: [] };
      sections.push(current);
    } else if (current) {
      current.widgets.push(item);
    } else {
      leading.widgets.push(item);
    }
  }
  return leading.widgets.length > 0 ? [leading, ...sections] : sections;
}

/**
 * Flatten editor sections back to a flat item list: a headingless leading
 * section contributes its cards bare, and every other section its divider
 * followed by its cards. An empty divider section is kept, so an in-progress
 * section a person has made but not filled survives a save (the page drops it
 * on read, exactly as it drops an empty default one).
 */
export function ungroupItems(sections: ItemSection[]): LayoutItem[] {
  const items: LayoutItem[] = [];
  for (const section of sections) {
    if (section.divider) items.push(section.divider);
    items.push(...section.widgets);
  }
  return items;
}

/**
 * The layout to render before the gate: the saved arrangement grouped into its
 * own dividered sections when there is one, otherwise the audience default
 * untouched. The gate (`visibleSections`) still runs last on the result, so an
 * empty custom section drops out exactly as an empty default one does.
 */
export function resolveEffectiveLayout(
  audience: AudienceId,
  stored: StoredEntry[] | null,
): SectionDef[] {
  if (stored === null) return LAYOUTS[audience];
  return sectionsFromItems(sanitizeEntries(stored));
}

/**
 * Gate a flat item list for the editor: a widget the caller may no longer see
 * is dropped, every divider is kept. The page gates through `visibleSections`
 * instead; this is the editor's equivalent, because the editor works on the
 * flat list and must keep the dividers a person is arranging.
 */
export function visibleItems(
  items: LayoutItem[],
  can: (permission: Permission) => boolean,
  isAppAdmin: boolean,
): LayoutItem[] {
  return items.filter((item) => isDivider(item) || WIDGETS[item.widget].gate(can, isAppAdmin));
}

/**
 * The widgets a person may add, gated. The catalog is a second surface with the
 * same secrets as the page, so it passes through the same gate - a widget the
 * caller cannot see must not be offered, or the list leaks what the page hides.
 */
export function widgetCatalog(
  can: (permission: Permission) => boolean,
  isAppAdmin: boolean,
): WidgetDef[] {
  return WIDGET_IDS.map((id) => WIDGETS[id]).filter((def) => def.gate(can, isAppAdmin));
}

/**
 * A fresh placement at the widget's default width and height. Its own function
 * so both "append" and "insert at a spot" build a card the same way, and the
 * default-size lookup lives in exactly one place.
 */
export function newPlacement(widget: WidgetId): LayoutEntry {
  const def = WIDGETS[widget];
  return { widget, span: def.defaultSpan, rows: def.defaultRows };
}

/** A fresh, unnamed, uncoloured, open section divider — the person tints it. */
export function newDivider(): DividerEntry {
  return { kind: "section", label: "", accent: "neutral" };
}

/**
 * The wire form for a PUT: items stripped to what is persisted. A widget always
 * carries a height (`sanitizeEntries`/`flattenDefaultToItems` fill it in); a
 * divider carries its kind, label and accent, and its collapse only when set.
 * Round-trips at the shape the person left it.
 */
export function toStored(entries: LayoutItem[]): StoredEntry[] {
  return entries.map((entry) => {
    if (isDivider(entry)) {
      const stored: StoredEntry = { kind: "section", label: entry.label, accent: entry.accent };
      if (entry.collapsed) stored.collapsed = true;
      return stored;
    }
    return {
      widget: entry.widget,
      span: entry.span,
      rows: entry.rows ?? WIDGETS[entry.widget].defaultRows,
    };
  });
}
