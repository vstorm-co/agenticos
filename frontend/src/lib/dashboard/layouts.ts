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
import type { PeriodPreset } from "./period";
import { WIDGETS, type Rows, type SectionAccent, type Span, type WidgetId } from "./registry";

/**
 * What one card overrides about itself, against a page that decides for all of
 * them.
 *
 * Absent on nearly every placement, and that is the default worth protecting: a
 * dashboard whose cards each answer about a different window is a dashboard
 * nobody can read across. These exist for the card that genuinely asks a
 * different question - the ninety-day trend beside the month's totals, the one
 * agent under review - and the card says so in its own header when it does.
 *
 * Which of these a widget accepts is its `options` in the registry; anything it
 * does not declare is dropped on read, so a knob that was removed from a widget
 * stops being sent to the API rather than lingering invisibly in a saved row.
 */
export interface WidgetOptions {
  /** Its own window, instead of the page's filter. */
  period?: PeriodPreset;
  /** Which presentation to draw in - one of the widget's declared styles. */
  style?: string;
  /** Narrow every number on this card to one agent. */
  agentId?: string;
  /** Narrow every number on this card to one person. */
  userId?: string;
}

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
   * Card height in fixed grid rows. Optional only for an arrangement saved
   * before heights existed - `sanitizeEntries` fills those in from the widget's
   * default, and the shipped default below sets every one explicitly.
   */
  rows?: Rows;
  /** i18n key under `dashboard`, overriding the widget's default title. */
  titleKey?: string;
  /** What this card overrides about itself. Absent = it follows the page. */
  options?: WidgetOptions;
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
 * The grid every arrangement renders in - the shipped default, a person's own,
 * and the editor between them.
 *
 * One grid, because a height only means something against a fixed row unit: it
 * pins the unit so a card's chosen height is the same number of pixels wherever
 * it sits, and `grid-flow-row-dense` lets a short card backfill the gap a tall
 * neighbour leaves. `SPAN_CLASS` and `ROW_CLASS` on each cell then place it in
 * two dimensions. The defaults used to auto-size instead, which meant the page
 * and the editor disagreed about the same layout.
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
 * The arrangement every new person lands on, whatever their role.
 *
 * One list rather than six curated ones, and it is not a simplification: the
 * layout only *proposes*, and `visibleSections` below disposes. A member is
 * refused every card in the first five bands and lands on their workspace; a
 * viewer is refused all but two. Six hand-written variants said the same thing
 * a permission already says, and drifted from each other every time a widget
 * was added to one of them.
 *
 * Every placement carries its height as well as its width, because both were
 * chosen on a real screen with real data in the cards - this is a page somebody
 * arranged and then asked to be the default, not a table of guesses. That is
 * also why the page renders a default in the same fixed-row grid as an arranged
 * one: a height nobody can see is not a default anybody chose.
 *
 * The order inside a band is the order it was arranged in, and it is the rule
 * the whole page is built on - a row holds cards of comparable natural height,
 * and a chart never sits beside a status list it dwarfs.
 */
const DEFAULT_SECTIONS: SectionDef[] = [
  // Deployment-wide, so app-admin only - every card here fails an
  // organization's gate and the band disappears with them.
  {
    id: "deployment",
    titleKey: "deployment",
    entries: [
      { widget: "platform", span: "s6", rows: "r2" },
      { widget: "health", span: "s6", rows: "r2" },
      { widget: "top-orgs", span: "s6", rows: "r3" },
      { widget: "platform-ratings", span: "s6", rows: "r3" },
    ],
  },
  // Untitled, and above every heading: it is the answer the rest of the page is
  // the detail of. It is *not* in the deployment band, where the arrangement
  // this default was taken from had put it - the four cards there are the
  // admin's alone, so for everybody else that band would render as a heading
  // reading "Deployment" over one card of their own organization's numbers.
  {
    id: "overview",
    titleKey: null,
    entries: [{ widget: "summary", span: "s12", rows: "r3" }],
  },
  {
    id: "attention",
    titleKey: "attention",
    entries: [
      { widget: "approvals", span: "s6", rows: "r3" },
      { widget: "budget-headroom", span: "s6", rows: "r2" },
      { widget: "mcp-health", span: "s6", rows: "r2" },
      { widget: "recent-failures", span: "s6", rows: "r3" },
      { widget: "knowledge-freshness", span: "s6", rows: "r3" },
      { widget: "channels", span: "s6", rows: "r3" },
      // Beside the channels rather than under Usage: an unattended run nobody is
      // watching is the definition of something that wants attention, and a
      // routine that has been failing every hour is invisible anywhere else on
      // this page (#594).
      { widget: "routines", span: "s6", rows: "r3" },
      { widget: "knowledge", span: "s6", rows: "r2" },
    ],
  },
  {
    id: "usage",
    titleKey: "usage",
    entries: [
      { widget: "runs", span: "s8", rows: "r3" },
      { widget: "outcomes", span: "s4", rows: "r3" },
      { widget: "surfaces", span: "s6", rows: "r3" },
      { widget: "agents", span: "s6", rows: "r3" },
      { widget: "spend", span: "s6", rows: "r3" },
      { widget: "model-mix", span: "s6", rows: "r3" },
      // The heatmap takes a row to itself - it is seven rows by twenty-four,
      // and anything beside it is either dwarfed or forced to a height it has
      // no content for.
      { widget: "activity-rhythm", span: "s12", rows: "r4" },
      { widget: "latency", span: "s6", rows: "r3" },
      { widget: "active-users", span: "s6", rows: "r3" },
      { widget: "top-people", span: "s12", rows: "r4" },
    ],
  },
  {
    id: "people",
    titleKey: "people",
    entries: [
      { widget: "members", span: "s6", rows: "r3" },
      { widget: "org-ratings", span: "s6", rows: "r3" },
    ],
  },
  /**
   * Where agents run code. The cards gate on `connections:view` - the read that
   * owner, admin, builder and now operator all hold (`ROLE_PERMS` in
   * `app/core/permissions.py`). The operator was the point of splitting the
   * permission: "why did that agent just get a 429" is their question, and it
   * needs the session list and the ceilings, not the authority to point a host
   * somewhere. See #129 and #449.
   */
  {
    id: "sandboxes",
    titleKey: "sandboxes",
    entries: [
      { widget: "sandbox-capacity", span: "s5", rows: "r3" },
      { widget: "sandbox-policy", span: "s7", rows: "r3" },
      { widget: "sandbox-sessions", span: "s12", rows: "r4" },
    ],
  },
  // The band a member's whole page is: their own agents, their own threads,
  // their own runs. Everything above it fails their gates and vanishes, so this
  // is what they land on - and it is why the personal cards are here rather
  // than in a variant nobody would keep in step.
  {
    id: "workspace",
    titleKey: "workspace",
    entries: [
      { widget: "my-agents", span: "s6", rows: "r4" },
      { widget: "conversations", span: "s6", rows: "r4" },
      { widget: "my-activity", span: "s12", rows: "r4" },
      { widget: "my-top-agents", span: "s6", rows: "r4" },
      { widget: "my-quality", span: "s3", rows: "r3" },
      { widget: "shared-with-you", span: "s3", rows: "r3" },
    ],
  },
];

/**
 * The same arrangement, with the agents card renamed for a viewer.
 *
 * A viewer's `my-agents` lists what was *shared with them* (`myAgentsPolicy`
 * narrows it), so calling those agents theirs is the one place the shared list
 * would say something untrue. It is the only per-audience difference left.
 */
function forViewer(sections: SectionDef[]): SectionDef[] {
  return sections.map((section) => ({
    ...section,
    entries: section.entries.map((entry) =>
      entry.widget === "my-agents"
        ? { ...entry, titleKey: "widgets.my-agents.sharedTitle" }
        : entry,
    ),
  }));
}

export const LAYOUTS: Record<AudienceId, SectionDef[]> = {
  app_admin: DEFAULT_SECTIONS,
  steward: DEFAULT_SECTIONS,
  operator: DEFAULT_SECTIONS,
  builder: DEFAULT_SECTIONS,
  member: DEFAULT_SECTIONS,
  viewer: forViewer(DEFAULT_SECTIONS),
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
