/**
 * Who sees which sections, in what order, at what widths.
 *
 * A layout is data: an ordered list of sections, each an ordered list of
 * `{widget, span, titleKey?}` entries. Span and title ride the entry rather
 * than a widget-keyed lookup, so one widget can appear twice on a page with
 * different widths and names (the viewer's "Agents shared with you" is the
 * my-agents widget under another title).
 *
 * The layout only proposes; the registry's gates dispose. The page filters
 * every entry through its widget's gate, and a section whose entries all fail
 * renders nothing - not even its heading.
 */

import type { Permission } from "@/types/permissions";
import { WIDGETS, type Rows, type SectionAccent, type Span, type WidgetId } from "./registry";

export interface LayoutEntry {
  /**
   * The entry kind, discriminating this widget placement from a
   * {@link DividerEntry}. Optional and defaulting to `"widget"` so the audience
   * defaults below — and every arrangement saved before dividers existed — read
   * as widgets without carrying the tag.
   */
  kind?: "widget";
  widget: WidgetId;
  span: Span;
  /**
   * Card height in fixed grid rows. Optional on the audience defaults, which
   * auto-size; a person's own arrangement fills it in (see `sanitizeEntries`),
   * so an edited card always has an explicit height to grow and shrink.
   */
  rows?: Rows;
  /** i18n key under `dashboard`, overriding the widget's default title. */
  titleKey?: string;
}

/**
 * A section divider: a full-width heading a person drops into their own
 * arrangement to break it into labelled, colour-tinted bands. It is not a
 * widget — it exposes no data and has no gate — so it carries only a free-text
 * label, an accent (a preset name, a custom `#rrggbb` hex, or neutral) and a
 * `collapsed` flag folding the section down to its heading, never a registry id.
 */
export interface DividerEntry {
  kind: "section";
  /** The free-text caption the person typed; may be empty (a bare rule). */
  label: string;
  accent: SectionAccent;
  /** Folded to just the heading on the page; the cards are hidden until reopened. */
  collapsed?: boolean;
}

/** One item in an arrangement: a widget placement or a section divider. */
export type LayoutItem = LayoutEntry | DividerEntry;

/** Narrow a {@link LayoutItem} to a section divider. */
export function isDivider(item: LayoutItem): item is DividerEntry {
  return item.kind === "section";
}

/** Narrow a {@link LayoutItem} to a widget placement. */
export function isWidget(item: LayoutItem): item is LayoutEntry {
  return item.kind !== "section";
}

export interface SectionDef {
  id: string;
  /** i18n key under `dashboard.sections`, or null for an untitled section. */
  titleKey: string | null;
  /**
   * A literal heading, used in place of `titleKey` for the sections a person's
   * own dividers create — those carry the text the person typed, not a key into
   * the catalog. Absent on the curated defaults, which are translated.
   */
  title?: string;
  /** The divider's colour, tinting this section's cards. Absent = neutral. */
  accent?: SectionAccent;
  /** Whether this section is folded to its heading — a custom divider's flag. */
  collapsed?: boolean;
  entries: LayoutEntry[];
}

export type AudienceId = "app_admin" | "steward" | "builder" | "operator" | "member" | "viewer";

/**
 * Role to audience. The app admin outranks the role; an unknown role - a
 * future custom one - lands on the member layout, the narrowest that still
 * shows the person their own work.
 */
export function resolveAudience(role: string, isAppAdmin: boolean): AudienceId {
  if (isAppAdmin) return "app_admin";
  switch (role) {
    case "owner":
    case "admin":
      return "steward";
    case "builder":
      return "builder";
    case "operator":
      return "operator";
    case "viewer":
      return "viewer";
    default:
      return "member";
  }
}

/**
 * Span to grid class. Literal strings so Tailwind's scanner sees them; below
 * `lg` everything stacks full-width. There is deliberately no span-to-pixels
 * table anywhere - charts measure themselves.
 */
export const SPAN_CLASS: Record<Span, string> = {
  s3: "lg:col-span-3",
  s4: "lg:col-span-4",
  s5: "lg:col-span-5",
  s6: "lg:col-span-6",
  s7: "lg:col-span-7",
  s8: "lg:col-span-8",
  s12: "lg:col-span-12",
};

/**
 * Row to grid class, the height counterpart of `SPAN_CLASS`. Literal strings so
 * Tailwind's scanner sees them; below `lg` every card stacks at its natural
 * height, so a `row-span` only bites where cards share a row.
 */
export const ROW_CLASS: Record<Rows, string> = {
  r2: "lg:row-span-2",
  r3: "lg:row-span-3",
  r4: "lg:row-span-4",
  r5: "lg:row-span-5",
  r6: "lg:row-span-6",
};

/**
 * The grid a person's own arrangement renders in — and the editor with it.
 *
 * Unlike the audience defaults (which auto-size and never set a row height),
 * an arranged grid pins a fixed row unit so a card's chosen height means the
 * same number of pixels wherever it sits, and `grid-flow-row-dense` lets a
 * short card backfill the gap a tall neighbour leaves. `SPAN_CLASS` and
 * `ROW_CLASS` on each cell then place it in two dimensions.
 */
export const ARRANGED_GRID_CLASS =
  "grid grid-cols-1 gap-4 lg:auto-rows-[5.5rem] lg:grid-cols-12 lg:grid-flow-row-dense";

/** The columns a span occupies, out of twelve — `s6` → 6. */
export function spanCols(span: Span): number {
  return Number(span.slice(1));
}

/** The rows a height occupies — `r3` → 3. */
export function rowCount(rows: Rows): number {
  return Number(rows.slice(1));
}

/** Widths in ascending order, for stepping and snapping. */
export const SPAN_ORDER: Span[] = ["s3", "s4", "s5", "s6", "s7", "s8", "s12"];

/** Heights in ascending order, for stepping and snapping. */
export const ROW_ORDER: Rows[] = ["r2", "r3", "r4", "r5", "r6"];

function stepInOrder<T>(order: T[], value: T, direction: -1 | 1): T {
  const index = order.indexOf(value);
  const next = Math.min(Math.max(index + direction, 0), order.length - 1);
  return order[next] as T;
}

/** The next wider or narrower width, clamped at the ends of the closed set. */
export function stepSpan(span: Span, direction: -1 | 1): Span {
  return stepInOrder(SPAN_ORDER, span, direction);
}

/** The next taller or shorter height, clamped at the ends of the closed set. */
export function stepRows(rows: Rows, direction: -1 | 1): Rows {
  return stepInOrder(ROW_ORDER, rows, direction);
}

function nearest<T>(order: T[], count: number, size: (value: T) => number): T {
  let best = order[0] as T;
  let bestGap = Math.abs(size(best) - count);
  for (const value of order) {
    const gap = Math.abs(size(value) - count);
    if (gap < bestGap) {
      best = value;
      bestGap = gap;
    }
  }
  return best;
}

/** The allowed width closest to a column count — for snapping a pointer resize. */
export function nearestSpan(columns: number): Span {
  return nearest(SPAN_ORDER, columns, spanCols);
}

/** The allowed height closest to a row count — for snapping a pointer resize. */
export function nearestRows(rows: number): Rows {
  return nearest(ROW_ORDER, rows, rowCount);
}

/**
 * Where agents run code, for the audiences that can watch a host.
 *
 * The cards gate on `connections:view` - the read that owner, admin, builder
 * and now operator all hold (`ROLE_PERMS` in `app/core/permissions.py`). The
 * operator was the point of splitting the permission: "why did that agent just
 * get a 429" is their question, and it needs the session list and the ceilings,
 * not the authority to point a host somewhere. See #129 and #449.
 */
const SANDBOX_SECTION: SectionDef = {
  id: "sandboxes",
  titleKey: "sandboxes",
  entries: [
    { widget: "sandbox-capacity", span: "s5" },
    { widget: "sandbox-policy", span: "s7" },
    { widget: "sandbox-sessions", span: "s12" },
  ],
};

const STEWARD_SECTIONS: SectionDef[] = [
  {
    id: "attention",
    titleKey: "attention",
    entries: [
      { widget: "approvals", span: "s7" },
      { widget: "recent-failures", span: "s5" },
      { widget: "budget-headroom", span: "s4" },
      { widget: "mcp-health", span: "s4" },
      { widget: "knowledge-freshness", span: "s4" },
    ],
  },
  {
    id: "usage",
    titleKey: "usage",
    entries: [
      { widget: "runs", span: "s8" },
      { widget: "outcomes", span: "s4" },
      { widget: "surfaces", span: "s6" },
      { widget: "agents", span: "s6" },
      { widget: "spend", span: "s6" },
      { widget: "model-mix", span: "s6" },
      { widget: "latency", span: "s4" },
      { widget: "active-users", span: "s8" },
      { widget: "top-people", span: "s12" },
    ],
  },
  {
    id: "people",
    titleKey: "people",
    entries: [
      { widget: "members", span: "s6" },
      { widget: "org-ratings", span: "s6" },
    ],
  },
  SANDBOX_SECTION,
  {
    id: "workspace",
    titleKey: "workspace",
    entries: [
      { widget: "my-agents", span: "s6" },
      { widget: "conversations", span: "s6" },
      { widget: "my-activity", span: "s12" },
    ],
  },
];

export const LAYOUTS: Record<AudienceId, SectionDef[]> = {
  app_admin: [
    {
      id: "deployment",
      titleKey: "deployment",
      entries: [
        { widget: "platform", span: "s8" },
        { widget: "health", span: "s4" },
        { widget: "top-orgs", span: "s7" },
        { widget: "platform-ratings", span: "s5" },
      ],
    },
    ...STEWARD_SECTIONS,
  ],
  steward: STEWARD_SECTIONS,
  operator: [
    {
      id: "attention",
      titleKey: "attention",
      entries: [
        { widget: "approvals", span: "s7" },
        { widget: "recent-failures", span: "s5" },
      ],
    },
    {
      id: "health",
      titleKey: "health",
      entries: [
        { widget: "outcomes", span: "s4" },
        { widget: "latency", span: "s3" },
        { widget: "org-ratings", span: "s5" },
      ],
    },
    {
      id: "usage",
      titleKey: "usage",
      entries: [
        { widget: "runs", span: "s8" },
        { widget: "surfaces", span: "s4" },
        { widget: "agents", span: "s6" },
        { widget: "spend", span: "s6" },
        { widget: "top-people", span: "s12" },
      ],
    },
    // The runtime allowlist and the capacity figure are an operator's to watch:
    // a host's ceilings answer "why did that agent get a 429", which they are
    // paged about and a builder is not. They hold `connections:view`, so the
    // cards' gate passes (#449).
    SANDBOX_SECTION,
    {
      id: "workspace",
      titleKey: "workspace",
      entries: [
        { widget: "my-agents", span: "s6" },
        { widget: "conversations", span: "s6" },
        { widget: "my-activity", span: "s12" },
      ],
    },
  ],
  builder: [
    {
      id: "build",
      titleKey: "build",
      entries: [
        { widget: "my-agents", span: "s7" },
        { widget: "conversations", span: "s5" },
      ],
    },
    {
      id: "adoption",
      titleKey: "adoption",
      entries: [
        { widget: "version-compare", span: "s6" },
        { widget: "agents", span: "s6" },
        { widget: "recent-failures", span: "s7" },
        { widget: "org-ratings", span: "s5" },
        { widget: "mcp-health", span: "s6" },
        { widget: "knowledge-freshness", span: "s6" },
      ],
    },
    {
      id: "usage",
      titleKey: "usage",
      entries: [
        { widget: "runs", span: "s8" },
        { widget: "outcomes", span: "s4" },
        { widget: "model-mix", span: "s6" },
        { widget: "surfaces", span: "s6" },
        { widget: "latency", span: "s4" },
        { widget: "active-users", span: "s8" },
        { widget: "top-people", span: "s12" },
      ],
    },
    // A builder is who gives an agent the code-execution capability, so the
    // memory ceiling their agents die on is their own question as much as an
    // operator's - both hold `connections:view`, which is what the cards gate on.
    SANDBOX_SECTION,
    {
      id: "activity",
      titleKey: null,
      entries: [{ widget: "my-activity", span: "s12" }],
    },
  ],
  member: [
    {
      id: "workspace",
      titleKey: null,
      entries: [
        { widget: "my-agents", span: "s7" },
        { widget: "conversations", span: "s5" },
        { widget: "my-activity", span: "s8" },
        { widget: "shared-with-you", span: "s4" },
        { widget: "my-top-agents", span: "s6" },
        { widget: "my-quality", span: "s6" },
      ],
    },
  ],
  viewer: [
    {
      id: "workspace",
      titleKey: null,
      entries: [
        { widget: "my-agents", span: "s8", titleKey: "widgets.my-agents.sharedTitle" },
        { widget: "shared-with-you", span: "s4" },
      ],
    },
  ],
};

/**
 * A section list with every entry the caller may not see removed, and every
 * section that ended up empty dropped - heading included. This is the whole of
 * the page's authorization, and it runs **last**, on whatever layout it is
 * handed: the audience default, or a person's own saved arrangement. A stored
 * preference can reorder or hide, but the gate here is what stops it revealing -
 * a widget that fails its gate is never mounted, so its queries are never
 * issued either, whichever layer put it in the list.
 */
export function visibleSections(
  sections: SectionDef[],
  can: (permission: Permission) => boolean,
  isAppAdmin: boolean,
): SectionDef[] {
  return sections
    .map((section) => ({
      ...section,
      entries: section.entries.filter((entry) => WIDGETS[entry.widget].gate(can, isAppAdmin)),
    }))
    .filter((section) => section.entries.length > 0);
}
